# MQTT, nhật ký và sức khỏe thiết bị

Trang này phân biệt phần đã có trong code với các mục của bản nháp chưa
triển khai. Sơ đồ và lệnh chạy: [PI_SERVICES.md](PI_SERVICES.md).

## Đường dữ liệu hiện tại

| Thành phần | Code hiện có | Giới hạn |
|---|---|---|
| Kết nối broker | `control/service.py`: TLS theo CA hệ thống, subscribe legacy/v2, Last Will, ACK/state/health/event/availability | Cần xác nhận ACL và topic với backend |
| Lệnh web | `control/protocol.py`: sáu trường legacy hoặc JSON v2 có ID và hạn dùng | Legacy cần `--allow-legacy-start`, không có ID/hạn dùng từ backend |
| Quyền bay | `flight/service.py` qua Unix socket cục bộ; một chủ MAVSDK | Chưa smoke test hai service trong HITL |
| Log | `observability/event_log.py`: JSONL theo phiên service, rotate theo kích thước, không tự xóa; `observability/export_logs.py` gộp thành CSV/JSONL | Chưa có một file/flight ID chung ngay lúc chạy, chưa đảm bảo dung lượng tối đa |
| Pi health | `observability/metrics.py` và Control Service: CPU, load, RAM/swap, nhiệt độ, disk, uptime, boot ID, RSS tiến trình, MQTT connected/RX/TX/reconnect và độ dài hàng lệnh | Chưa có undervoltage, Wi-Fi RSSI, camera |
| Pixhawk state | `GpsMissionControl.status()`: mode, armed, landed, position và tuổi telemetry | Chưa thu đầy đủ pin, GPS quality, StatusText/failsafe |
| Runtime config | `config/defaults.json`, `config/schema.json`, `control/config_manager.py`: interval state/health; lệnh `debug_set` bật DEBUG có hạn | Chưa kiểm thử tải log trên Pi |
| Camera/OTA | `camera_status` và `ota_status` trả `available=false` | Không có camera adapter hay cập nhật từ xa |

Control service tiếp tục giữ MQTT khi flight service không phản hồi và
publish `state.online=false`. Hai tiến trình lưu log riêng trên Pi; log
vẫn ghi khi MQTT mất kết nối. Không có outbox phát lại ACK/event sau mất
mạng. MQTT callback chỉ xếp bản tin vào hàng; luồng chính mới gửi IPC.

## Topic và ý nghĩa ACK

| Topic | Chiều | Nội dung | Retain |
|---|---|---|---|
| `lac/<id>/control` | backend → Pi | Sáu trường legacy trong một payload | Phải OFF |
| `lac/<id>/v2/command` | backend → Pi | JSON v2 có ID/hạn dùng | Phải OFF |
| `lac/<id>/v2/ack` | Pi → backend | `received`, `accepted` hoặc `rejected` | OFF |
| `lac/<id>/v2/state` | Pi → backend | Snapshot trạng thái flight, thời điểm quan sát | ON |
| `lac/<id>/v2/health` | Pi → backend | Snapshot Pi health | ON |
| `lac/<id>/v2/event` | Pi → backend | Nhận/chấp nhận/từ chối lệnh, thay đổi trạng thái hoặc mất flight service | OFF |
| `lac/<id>/v2/availability` | Pi → backend | Online/offline và boot ID khi online | ON, có Last Will |

`received` chỉ nói service MQTT nhận payload. `accepted` nói flight
service đã xử lý yêu cầu; telemetry/phase mới xác nhận mode và đích.
Backend chưa được xác nhận đang đọc các topic v2. `/event` hiện chỉ có
sự kiện lệnh, thay đổi trạng thái và mất flight service, chưa phải toàn bộ log. Không
xuất payload `/data` hoặc `/debug` legacy.

So với vòng đời ACK trong bản nháp:

| Mức | Hiện trạng |
|---|---|
| `received` | Đã publish khi payload được parse và có ID mới |
| `accepted` | Đã publish khi Flight Service nhận lời gọi mà không trả lỗi |
| `rejected` | Đã publish cùng lý do khi validation/IPC/controller từ chối |
| `executing` | Chưa gắn `command_id` với phase đang thực hiện |
| `completed` | Chưa publish ACK hoàn thành; phải đọc `/state` và telemetry |
| `failed` | Chưa publish ACK kết thúc thất bại; lỗi xuất hiện trong event/state/log |

Broker username/password và ACL là lớp xác thực hiện tại. Code chưa có
phân quyền ứng dụng riêng theo loại lệnh hoặc người vận hành.

## Nội dung log và mục tiêu hoàn thiện

Mỗi dòng JSONL hiện có `ts_utc`, `monotonic_ms`, `boot_id`, `session_id`,
`service`, `record_type`, `severity`, `event`, `message` và các trường sự
kiện thêm như `command_id`, `mission_id`, phase hoặc metrics. `flight`
service ghi yêu cầu/chấp nhận/từ chối và thay đổi phase/mode/armed/landed;
`control` service ghi kết nối MQTT, lệnh và mẫu sức khỏe Pi. ULog trên SD
Pixhawk vẫn là nguồn chi tiết về điều khiển bay.

Các việc còn thiếu theo bản nháp:

1. Gắn `flight_id` xuyên control/flight/log/QGC ULog, ghi tiến độ từng lệnh
   `requested → ACK PX4 → mode confirmed → arrived` và gom log theo chuyến.
2. Đối chiếu mức DEBUG theo module trên Pi; tiếp tục bảo đảm không tắt
   ERROR/CRITICAL, ARM, LAND và thay đổi phase.
3. Thêm sức khỏe Pixhawk (battery, GPS fix/accuracy, failsafe/status text),
   nguồn Pi, Wi-Fi, camera và ngưỡng cảnh báo đã đo trên thiết bị thật.
4. Giới hạn kho log và cảnh báo đầy đĩa, xuất CSV/tải log qua kênh xác thực.
5. Lưu ID lệnh bền qua reboot, phối hợp quyền MQTT/ACL với backend. Hiện chỉ
   giữ 4096 ID gần nhất trong RAM; một
   payload legacy giống hệt sau reboot hiện không thể phân biệt bản tin cũ.
6. Mở rộng `/v2/event` cho cảnh báo đã phân loại và thêm outbox có giới
   hạn cho ACK/event. Không phát lại lệnh bay cũ.

Khi cần xem toàn bộ sự kiện trên một bảng, xuất từ log gốc trên Pi (không
xóa hoặc sửa log gốc):

```bash
python3 pi/observability/export_logs.py --log-dir /var/lib/uav/logs \
  --output /var/lib/uav/combined-review.csv --format csv
```

## Cấu hình, camera và OTA

Hiện MQTT chỉ được đổi chu kỳ state/health và bật DEBUG có hạn. Không nhận
tham số PX4, motor mapping, calibration, mật khẩu hoặc lệnh shell qua MQTT.
Camera chưa có driver; các trường resolution/fps/bitrate/frame drop chỉ
được thêm khi adapter và cảm biến tương ứng có mặt.

Payload v2 bật debug dùng dạng sau; đổi `level` thành `INFO` để tắt sớm:

```json
{
  "type": "debug_set",
  "params": {"module": "flight", "level": "DEBUG", "duration_s": 600}
}
```

Các trường bao ngoài `schema`, `command_id`, `mission_id`, `issued_at_utc`
và `expires_at_utc` vẫn bắt buộc như mọi lệnh v2.

OTA (*Over-the-Air*) là cập nhật code trên Pi qua mạng. Một luồng OTA đầy
đủ cần gói có chữ ký/hash, kiểm tra version/thiết bị, UAV disarmed/on ground,
nguồn và dung lượng, staging, health check và rollback. Không có luồng đó
trong code hiện tại. Flash firmware Pixhawk là quy trình khác và không được
gộp với cập nhật code Pi. Chỉ một IP/URL tải file không đủ để gọi là OTA.

QGC không subscribe MQTT. Cảnh báo do Pi tạo hiện chưa được bridge sang
MAVLink STATUSTEXT của QGC; không coi một bản tin MQTT là thông báo QGC.
