# mineru-parser

`mineru-parser` 把 MinerU 的异步文档解析流程封装成同步 Python 调用：传入 PDF 链接提交解析任务，调用方通过结果句柄等待进度，成功后返回结果包的下载地址。适合后端服务、批处理脚本和离线文档处理等需要“提交 → 等待 → 取结果”的场景。

主要功能：

- **提交并等待**：`submit()` 返回 `AsyncResult`，由句柄的 `wait()` 完成等待；也可以先提交、稍后再等待；
- **任务恢复**：持久化 `task_id` 后，可在之后的进程里通过 `resume()` 恢复等待，不会重复提交任务；
- **稳健轮询**：自动处理指数退避、随机抖动、服务端 `Retry-After` 与连续错误上限，偶发故障不会立即中断；
- **等待边界**：支持相对超时和绝对截止时间，超时异常携带最后已知的任务状态；
- **进度回调**：状态或解析页数变化时触发回调，便于上报进度；
- **错误分类**：认证、额度、瞬时、执行与超时错误分别抛出，便于调用方决定重试策略；
- **结果交付**：成功时返回 MinerU 结果包的 `zip_url`，下载与解压由调用方处理；
- **可选下载器**：`ResultDownloader` 把结果包 URL 流式读入 `io.BytesIO`，统一处理超时、重试、SSRF 防护与内存上限；不使用时 API 客户端行为不变。

```python
from mineru_parser import MinerUApiClient

with MinerUApiClient() as client:  # API Key 默认读取 MINERU_API_KEY
    # 提交解析任务，立即拿到可等待的结果句柄
    submission = client.submit("https://example.com/paper.pdf", data_id="doc-42")
    result = submission.wait(timeout=600, on_update=lambda s: print(s.state))
    print(result.zip_url)

    # 进程重启后：从持久化的 task_id 恢复等待，不会重复提交
    resumed = client.resume(submission.task_id)
    result = resumed.wait(timeout=600)
```

`MinerUApiClient` 仍然只交付 `zip_url`，不负责下载与解压；需要直接拿到内存流时，可选用独立的 `ResultDownloader`：

```python
import zipfile

from mineru_parser import MinerUApiClient, ResultDownloader

with MinerUApiClient() as client, ResultDownloader() as downloader:
    result = client.submit("https://example.com/paper.pdf").wait(timeout=600)
    stream = downloader.resolve(result.zip_url)  # io.BytesIO，游标位于 0
    with zipfile.ZipFile(stream) as archive:
        ...
```

下载器默认限制单次响应体为 50 MiB、总耗时为 300 秒，并拒绝非公网目标与 HTTPS 降级重定向。若注入自定义 `requests.Session`，请将其内部重试次数设为 0（下载器的 `DownloadRetryPolicy` 是唯一重试层），且不要携带全局 `Authorization` / `Cookie` 头或 `session.auth`。

## 数据管道

```mermaid
flowchart LR
    %% 样式定义
    classDef clientStyle fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef taskStyle fill:#e1f5fe,stroke:#0277bd,stroke-width:2px,color:#01579b;
    classDef pollStyle fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c;
    classDef depStyle fill:#eceff1,stroke:#546e7a,stroke-width:1px,color:#263238;
    classDef dataStyle fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef extStyle fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c;
    classDef serverStyle fill:#fce4ec,stroke:#ad1457,stroke-width:2px,color:#880e4f;
    classDef boundaryStyle fill:#ffffff,stroke:#90a4ae,stroke-width:1px,stroke-dasharray: 4 3,color:#546e7a;

    %% 外部输入 / 输出
    PDF["PDF File URL"]:::extStyle
    CALLER["调用方 (Caller)"]:::extStyle
    SERVER["MinerU API Server"]:::serverStyle

    %% 核心管道：每个组件的实线节点写职责，虚线节点写边界
    subgraph CORE["mineru-parser 核心管道"]
        direction LR

        subgraph CLIENTBOX["MinerUApiClient｜配置 + 任务工厂"]
            direction TB
            CLIENT["职责<br/>• 凭证 / base_url / timeout<br/>• Session 生命周期（连接池共享）<br/>• submit · resume · 内部状态查询<br/>• 按 PollPolicy 创建 Poller"]:::clientStyle
            CLIENT_X["边界<br/>• 不保存任务状态<br/>• 不执行轮询 / 等待<br/>• 不解释任务终态<br/>• data_id 仅用于对账，不是幂等键"]:::boundaryStyle
        end

        subgraph TRANSPORTBOX["MinerUTransport｜wire 协议"]
            direction TB
            TRANSPORT["职责<br/>• HTTP 请求构造 / 响应解析<br/>• HTTP / 业务错误分类"]:::depStyle
            TRANSPORT_X["边界<br/>• 不持有任务状态<br/>• 不做轮询<br/>• 不做任务终态解释"]:::boundaryStyle
        end

        subgraph TASKBOX["AsyncResult｜结果句柄"]
            direction TB
            TASK["职责<br/>• 持有 task_id / data_id<br/>• 缓存最近状态 / 终态结果<br/>• 解释终态：返回结果或抛异常<br/>• 终态后 wait() 不再访问网络"]:::taskStyle
            TASK_X["边界<br/>• 不直接发 HTTP<br/>• 不决定轮询节奏<br/>• 非线程安全"]:::boundaryStyle
        end

        subgraph POLLBOX["Poller｜轮询节奏"]
            direction TB
            POLLER["职责<br/>• 退避 + 抖动 · Retry-After 优先<br/>• 连续错误上限<br/>• timeout / deadline<br/>• 状态 / 进度变化触发 on_update"]:::pollStyle
            POLLER_X["边界<br/>• 不解释任务成败<br/>• 不管理任务状态"]:::boundaryStyle
        end

        STATUS["MinerUTaskStatus<br/>state · progress · full_zip_url"]:::dataStyle
        RESULT["MinerUTaskResult<br/>zip_url · provider_task_id · data_id<br/>产物边界：仅提供 zip_url，不负责下载 / 解压"]:::dataStyle
    end

    %% 提交：Client 做配置与工厂，Transport 只讲 wire 协议
    PDF -->|"uri"| CLIENT
    CLIENT -- "submit / trace 委托" --> TRANSPORT
    TRANSPORT -- "POST /extract/task<br/>GET /extract/task/{id}" --> SERVER
    SERVER -- "task_id / 任务详情 JSON" --> TRANSPORT
    TRANSPORT -- "task_id / ExtractionTaskDetail" --> CLIENT

    %% 句柄：Client 只负责创建 / 恢复，不接管任务生命周期
    CLIENT -- "构造并返回句柄" --> TASK
    CLIENT -. "resume(task_id)：从持久化 id 恢复<br/>不发起网络请求" .-> TASK

    %% 等待：AsyncResult 定义语义，Poller 只决定节奏
    TASK -- "wait()：Poller.run(fetch = result.refresh)" --> POLLER
    POLLER -- "循环 fetch()" --> TASK
    TASK -- "refresh()：client._trace(task_id)（内部）" --> CLIENT
    CLIENT -- "normalize_status()" --> STATUS
    STATUS -- "写入 status 缓存" --> TASK

    %% 终态：只有 Task 解释成败
    TASK -- "succeeded" --> RESULT
    TASK -. "failed / canceled → MinerUExecutionError<br/>timeout → MinerUTimeoutError" .-> CALLER
    RESULT --> CALLER

    %% 子图样式微调
    style CORE fill:#fafafa,stroke:#b0bec5,stroke-width:1px,stroke-dasharray: 3 3
    style CLIENTBOX fill:#f5f9ff,stroke:#90caf9,stroke-width:1px
    style TRANSPORTBOX fill:#f7f9fa,stroke:#b0bec5,stroke-width:1px
    style TASKBOX fill:#f1faff,stroke:#81d4fa,stroke-width:1px
    style POLLBOX fill:#faf5fc,stroke:#ce93d8,stroke-width:1px
```

