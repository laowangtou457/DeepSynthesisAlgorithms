# DEV-20261113-003　T-111 实施＋独立验收：跑测器具去 cwd 依赖、guided 自证、版本 fail-fast

| 项 | 内容 |
|---|---|
| 编号 | `DEV-20261113-003` |
| 日期 | 2026-11-13 |
| 动作类型 | 代码 / 器具（实施 ＋ QA 独立回归） |
| 关联 | `T-111`、`ISSUE-086`（根治落地）、`DEV-20261112-011`（根因）、`DEV-20261113-002`、`T-110` |
| 结论 | `T-111` 三件全部落地，QA 独立回归 **6/6 PASS**、零缺陷；`ISSUE-086` 转 🟩（根治落地）；验收③「真机复跑 2 轮」待本机 vLLM 恢复后执行 |
| 涉及代码改动 | `03-工程代码/.wb-e2e/_ab_t101.py`（43632 B，纯 LF 守恒）；**`app/` 生产代码零改动** |

## 1. 改动内容（对应 `T-111` 三项要求）

1. **① `.env` 与 cwd 解耦**：器具入口显式解析工程根 `.env`（`ROOT/.env`，自实现 KEY=VALUE 解析，无第三方依赖），`APP_` 前缀键注入 `os.environ`（不覆盖外部已显式设置值）；`FIXED_ENV` 照旧在其后覆盖，优先级语义不变。
2. **② 启动头自证**：启动头打印 `guided_mode` 生效值，与 `inference_backend`/`vllm_base_url`/`vllm_model` 同排；并回读 `os.environ` 原始值与 settings 生效值比对（不一致即内部 bug，直接暴露）。
3. **③ 版本 fail-fast**：`_check_guided_compatibility()`——GET `{base_url 去 /v1}/version`（vLLM 版本端点在根路径，不在 `/v1` 下）；guided=`structured_outputs` 且服务端主次版本 < 0.12 ⇒ 明确报错并 `sys.exit(2)`；服务端不可达 ⇒ WARNING 继续（后端调用自会暴露）；`response_format`/`guided_json`/`off` 不触发（`response_format` 跨版本通用）。
4. **新增 `AB101_PREFLIGHT=1` 预检模式**：只跑 ①②③＋打印关键配置后退出 0，不烧 GPU——供验收与日常自检。

## 2. QA 独立回归（严过关，6/6 PASS）

| # | 验收项 | 结果 |
|---|---|---|
| 1 | `py_compile` ＋ 纯 LF 守恒（无 `\r` 字节） | PASS |
| 2 | 双 cwd（`.wb-e2e` 与 `03-工程代码`）预检输出**同一** `guided_mode=response_format`、exit 0 | PASS |
| 3 | fail-fast：`structured_outputs` ＋ 假端点返回 `0.10.2` ⇒ **非零退出**、报错明确（假端点测后关闭） | PASS |
| 4 | 越界检查：`git status` 无 `app/` 新增改动 | PASS |
| 5 | 调试痕迹清理（临时目录已删） | PASS（cleanup 1 项已执行） |
| 6 | `AB101_FIXTURE_VERSION=v1` 分支参数解析正常（预检级，不烧 GPU） | PASS |

遗留（deferred）：验收③「以新器械真机复跑 2 轮、产物形态与主序列 1~7 轮一致」——需本机 8001 vLLM 在线（11-13 重启后未起），恢复后执行约 1h GPU。

## 3. 边界与登记事项

- **`app/core/config.py` 未动**（`env_file=".env"` 仍为 cwd 相对）：生产服务由部署脚本从固定 cwd（`03-工程代码`）启动，不受影响；台账认可的治本口径即器具侧三件（`ISSUE-086` 行），故器具侧落地即根治。
- **`.wb-e2e/` 整体排除出版本控制**（`.gitignore`，git 内 0 文件）⇒ 本修复与 `_r6_monitor.py`、`_real_e2e.py` 等**同属「换机须重建」资产**——与 `.git/hooks/pre-push`、`E:\_受控区\` 同族，克隆后须另行投放。
- 验收方法备注：fail-fast 判定路径以**本地假端点**（`http.server` 返回 `{"version":"0.10.2"}`，空闲端口）等价触发，实测 exit ≠ 0；真服务端 0.10.2 场景在 18001 隧道在线时亦核验过版本读取路径。
- 团队协作留痕：本批由主理人按 BugFix 快捷路径编排（工程师寇豆码实施 → QA 严过关独立回归），两条上下文均含项目纪律（LF 写盘、真名不入库、不烧 GPU）。
