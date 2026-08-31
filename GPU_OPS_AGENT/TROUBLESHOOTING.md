# 📋 GPU Ops Agent 常见问题与解决方案

## ⚠️ 关键问题：前端/后端无法从外网访问

### 问题症状
- 本机可以访问 `http://localhost:8035`
- 但从外网无法访问 `http://port8035.ocp312proabscxpco-tr020002-0-svc.gps.cloud.ctripcorp.com`

### ❌ 错误的启动方式
```bash
# 这样启动只能本机访问！
python3 -m uvicorn main:app --port 8030
python3 -m uvicorn frontend_server:app --port 8035
```

### ✅ 正确的启动方式
```bash
# 必须加 --host 0.0.0.0
python3 -m uvicorn main:app --host 0.0.0.0 --port 8030
python3 -m uvicorn frontend_server:app --host 0.0.0.0 --port 8035
```

### 为什么？
- `--host 0.0.0.0` = 服务监听所有网卡/网络接口
- `--host 127.0.0.1` 或 `--host localhost` = 只监听本机回环，外网无法访问

---

## 🚀 快速启动命令

**方法 1：使用启动脚本（推荐）**
```bash
bash START_SERVICES.sh
```

**方法 2：手动启动**
```bash
# 后端
python3 -m uvicorn main:app --host 0.0.0.0 --port 8030 &

# 前端
python3 -m uvicorn frontend_server:app --host 0.0.0.0 --port 8035 &
```

---

## 📱 访问地址

| 用途 | 地址 | 备注 |
|------|------|------|
| 前端（外网） | http://port8035.ocp312proabscxpco-tr020002-0-svc.gps.cloud.ctripcorp.com | 主要地址 |
| 前端（本机） | http://localhost:8035 | 仅限本机 |
| 前端（IP） | http://10.43.32.44:8035 | 内网 IP |
| 后端 API | http://port8030.ocp312proabscxpco-tr020002-0-svc.gps.cloud.ctripcorp.com/api | 用于测试 |

---

## 🔄 重启服务

```bash
# 杀死所有旧进程
pkill -9 uvicorn

# 用脚本重启
bash START_SERVICES.sh
```

---

## 🧹 清除浏览器缓存

前端页面更新后，需要硬刷新才能看到最新内容：

| 浏览器 | 快捷键 |
|--------|--------|
| Chrome/Edge/Firefox | `Ctrl+Shift+R` |
| Mac Chrome/Edge | `Cmd+Shift+R` |
| Mac Safari | `Cmd+Option+E` 然后刷新 |

---

## 📝 已知问题列表

### 1. CPU 卡型在 GPU Summary 中显示
**状态**：✅ 已修复
- **原因**：后端未过滤 gpu_type="cpu" 的节点
- **解决**：在 `api/dashboard_routes.py` 的 `_group_facts()` 中添加过滤逻辑
- **修复代码**：
  ```python
  if label_name == "gpu_type" and label == "cpu":
      continue  # 跳过 CPU 类型
  ```

### 2. 外网无法访问前端/后端
**状态**：✅ 已修复
- **原因**：启动时未指定 `--host 0.0.0.0`
- **解决**：始终使用 `--host 0.0.0.0` 启动服务

---

## ✨ 检查清单

启动服务前，确认：
- [ ] 后端启动命令包含 `--host 0.0.0.0 --port 8030`
- [ ] 前端启动命令包含 `--host 0.0.0.0 --port 8035`
- [ ] 两个服务都成功启动（查看日志无错误）
- [ ] 浏览器已硬刷新清除缓存
- [ ] 访问外网地址能打开页面
