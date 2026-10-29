# Hai service chạy trên Pi: web là luồng điều khiển chính

Kiến trúc triển khai mới tách quyền sở hữu Pixhawk khỏi kết nối mạng:

```text
Web/backend -> MQTT broker -> control service -> Unix socket -> flight service -> MAVSDK -> PX4
                              |                             |
                              +-- CPU/RAM/temp/disk         +-- FSM/GPS/return/LAND
                              +-- JSONL log                 +-- JSONL log
```

## Trách nhiệm và file

| Thành phần | File chính | Có quyền gì |
|---|---|---|
| Control service | `pi/control/service.py` | Giữ MQTT, lọc retain/ID/hạn dùng, ACK, health/config, chuyển lệnh qua IPC; **không import/call MAVSDK** |
| Flight service | `pi/flight/service.py` | Chủ duy nhất của MAVSDK/Pixhawk, gọi `GpsMissionControl`, trả status |
| Định tuyến lệnh | `pi/control/command_router.py`, `pi/flight/commands.py` | Tách lệnh quản lý khỏi lệnh bay; chỉ phía flight gọi bộ điều khiển |
| Cấu hình | `pi/control/config_manager.py` | Cho phép thay đổi các khoảng publish đã được kiểm tra |
| Giao thức | `pi/control/protocol.py` | Chuyển payload sáu trường hiện tại thành một `gps_start`; kiểm tra schema v2 |
| Monitor MQTT | `pi/control/monitor.py` | Xem payload legacy chỉ đọc, không ra lệnh bay |
| IPC | `pi/ipc/client.py`, `server.py`, `messages.py` | JSON qua Unix socket cục bộ, không mở cổng mạng |
| Log/metrics | `pi/observability/` | JSONL, CPU, RAM, nhiệt độ, disk, uptime và RSS tiến trình |
| Console kỹ thuật | `pi/console.py` | Thử local NED; `fly x y` không thuộc API web |

Cấu trúc hiện tại bám theo ranh giới này:

```text
controller/pi/
├── console.py                 # terminal thử nghiệm, nằm ngoài hai service
├── control/
│   ├── service.py             # vòng đời Control Service
│   ├── mqtt_client.py         # kết nối MQTT TLS
│   ├── protocol.py            # kiểm tra payload web
│   ├── command_router.py      # quản lý hoặc chuyển lệnh sang Flight
│   ├── config_manager.py
│   ├── camera_manager.py      # hiện chỉ báo chưa có adapter
│   └── ota_manager.py         # hiện chỉ báo chưa triển khai OTA
├── flight/
│   ├── service.py             # chủ duy nhất của MAVSDK
│   ├── commands.py            # ánh xạ lệnh web sang bộ điều khiển
│   ├── pixhawk.py
│   ├── offboard_control.py
│   ├── gps_mission.py
│   └── flight_policy.py
├── ipc/
│   ├── client.py
│   ├── server.py
│   └── messages.py
├── config/
│   ├── defaults.json
│   └── schema.json
└── observability/
    ├── event_log.py
    ├── metrics.py
    └── export_logs.py
```

`monitor.py` trong `control/` chỉ quan sát payload MQTT để chẩn đoán. Nó
không phải service thứ ba, không sở hữu MAVSDK và không gửi lệnh bay.

Luồng web hỗ trợ `gps_start`, `pause`, `resume`, `cancel`, `return_home`,
`return_height`, `land` và `disarm`. `disarm` cưỡng bức có thể làm UAV rơi,
nên schema v2 bắt buộc `params.confirm_force=true`. Không có lệnh web
`fly x y`.

Payload legacy hiện tại vẫn dùng được:

```text
c:spd:0.5;c:height:3;c:startlat:47.3977760;c:startlong:8.5456050;c:endlat:47.3978100;c:endlong:8.5456500;
```

Nó được hiểu nguyên tử là `gps_plan(...)` rồi `gps_start()`. Vì legacy không
có `command_id` từ backend, Pi tạo ID theo payload và chặn khi ID đó còn
trong 4096 ID gần nhất của phiên. Retain luôn bị bỏ qua. Backend nên chuyển sang
`lac/<deviceID>/v2/command` để có ID, hạn dùng và các nút điều khiển khác.
Khi A=B trong `xy_tolerance` và nằm trong `start_error_m` (mặc định 5 m)
quanh GPS hiện tại, `gps_start` là nhiệm vụ
`vertical_only`: một waypoint tại chỗ tới độ cao đã chọn rồi HOLD.

## Chạy thử thủ công trong HITL trên PC

Từ gốc repository, sau khi Gazebo đang chạy và tạo UDP
`127.0.0.1:14540`, mở ba terminal. Terminal 1 là tiến trình duy nhất sở
hữu Pixhawk:

```bash
simulation/.venv/bin/python controller/pi/flight/service.py \
  --profile hitl --connection udpin://127.0.0.1:14540 \
  --height 2.5 --gps-max-height 3 --gps-max-speed 0.5 \
  --socket /tmp/uav-flight.sock --enable-actuation
```

Terminal 2 giữ MQTT và hỏi mật khẩu (không ghi mật khẩu vào lệnh):

```bash
simulation/.venv/bin/python -m pip install \
  -r controller/pi/flight/requirements.txt -r controller/pi/control/requirements.txt
simulation/.venv/bin/python controller/pi/control/service.py \
  --device-id uav01 --username MQTT_USER \
  --flight-socket /tmp/uav-flight.sock --allow-legacy-start
```

Sau đó nút “Gửi nhiệm vụ & cất cánh” trên web gửi sáu trường legacy và
control service gọi flight service. Xem trạng thái/ACK ở:

- `lac/uav01/v2/ack`
- `lac/uav01/v2/state`
- `lac/uav01/v2/health`
- `lac/uav01/v2/availability`
- `lac/uav01/v2/event` (thay đổi trạng thái/mất flight service)

Log nằm trong `session-logs/services/*.jsonl`. Mỗi dòng có thời gian UTC,
boot/session, service, severity, event, command/mission ID và dữ liệu có cấu
trúc. Log xoay file theo kích thước nhưng mặc định không tự xóa file cũ.
Để tạo một bảng CSV gồm thời gian, service, sự kiện, CPU/RAM/nhiệt độ,
phase và lệnh từ hai log gốc, dùng
`python3 pi/observability/export_logs.py --log-dir session-logs/services --output combined-review.csv --format csv`
từ thư mục `controller/`. File nguồn không bị thay đổi.

Web legacy hiện chưa có các nút Pause/Resume/LAND. Giữ một terminal để mở
console giám sát qua **chính flight service**; nó dùng Unix socket và không
mở MAVSDK hoặc tranh UDP 14540:

```bash
simulation/.venv/bin/python controller/pi/flight/client.py
```

Tại `UAV-REMOTE>` có thể gõ `status`, `pause`, `resume`, `cancel`,
`return-home`, `return-height`, `land`, `disarm`, `help` và `exit`. `disarm`
gửi dừng motor khẩn cấp ngay, không có bước xác nhận thứ hai; UAV sẽ rơi nếu
đang trên không, vì vậy LAND vẫn là cách kết thúc bình thường. `exit`/Ctrl+C chỉ
đóng client, không gửi LAND. Chỉ gõ `land` khi muốn hạ cánh; sau ACK, chờ
`status`/QGC xác nhận ON_GROUND và DISARM trước khi đóng service hoặc Gazebo.
Chế độ một lệnh vẫn dùng được, ví dụ `flight/client.py status`,
`flight/client.py land` hoặc emergency `flight/client.py disarm`.

## Chạy tự động trên Pi

Hai unit trong `controller/systemd/` giả định bản phát hành đang dùng được
trỏ bởi `/home/pi/uav/current/controller`. Tạo `/etc/uav/uav.env`:

Unit mẫu mở flight service ở chế độ **chỉ đọc**. Sau khi thử HITL trên đúng
đường kết nối và kiểm tra quyền điều khiển, người vận hành mới thêm
`--enable-actuation` vào unit flight ở bản triển khai đã phê duyệt.

```ini
UAV_PROFILE=hardware
UAV_CONNECTION=udpin://127.0.0.1:14540
UAV_HEIGHT=2.0
UAV_GPS_MAX_HEIGHT=3.0
UAV_GPS_MAX_LEG=10.0
UAV_GPS_MAX_SPEED=0.5
UAV_DEVICE_ID=uav01
UAV_MQTT_USERNAME=MQTT_USER
UAV_MQTT_HOST=mqtt.lacais.com
UAV_MQTT_PORT=8883
```

Đặt riêng mật khẩu vào `/etc/uav/mqtt-password`. Service chạy với user
`pi`, nên file và thư mục `/etc/uav` phải cho `pi` quyền đọc/traverse
(ví dụ file `root:pi` mode `0640` và directory `root:pi` mode `0750`).
Không commit hai file này.
Chỉ cài/enable systemd sau khi hai lệnh thủ công chạy đúng trên đúng Pi.

## Phần đã có và phần chưa giả vờ là đã có

| Mục tiêu bản nháp | Mức đáp ứng hiện tại |
|---|---|
| Hai service Control/Flight, một chủ MAVSDK | Đã có và có test khóa ranh giới import |
| Web GPS A→B qua MQTT → IPC | Đã có code; chưa smoke test HITL end to end |
| Log JSONL + xuất CSV + health Pi | Đã có phần nền; chưa gắn `flight_id`/ULog |
| Debug theo module qua MQTT | Đã có `DEBUG/INFO` có thời hạn; chưa đo tải trên Pi |
| ACK đủ vòng đời | Mới có `received/accepted/rejected`; thiếu `executing/completed/failed` |
| Alert tự động và PX4 StatusText/QGC bridge | Chưa có |
| Camera manager | Chỉ có capability status; chưa có camera adapter |
| OTA code Pi | Chỉ có capability status; chưa download/verify/stage/rollback |
| Firmware Pixhawk từ xa | Chưa triển khai và tách khỏi OTA Pi |

- Đã có: tách hai process, IPC, web GPS/flight routing, ACK/state/health,
  JSONL log, metrics Pi, allowlist config và mẫu systemd.
- Payload sáu trường legacy chỉ tự cất cánh khi control service được mở
  bằng `--allow-legacy-start`; mẫu systemd không bật cờ này. Dùng lệnh v2
  có ID/hạn dùng cho đường triển khai chính.
- `debug_set` v2 dùng `params.level=DEBUG|INFO` cho module `mqtt`, `control`,
  `flight`, `pixhawk`, `camera`, `ota`, `health` trong 1–3600 giây. DEBUG được giới hạn
  tối đa một bản ghi/giây cho từng sự kiện; log quan trọng vẫn luôn được ghi.
  Các module chưa có nguồn dữ liệu sẽ chỉ ghi thay đổi cấu hình debug; chức
  năng này chưa kiểm thử trên Pi với tải thực tế.
- Log hiện ghi sự kiện lệnh, thay đổi trạng thái và mẫu sức khỏe Pi, chưa có
  toàn bộ status text PX4, pin/GPS chi tiết, `flight_id` xuyên hai service,
  hay đầy đủ bảng “requested → mode confirmed → arrived” cho từng lệnh.
- Chống lặp `command_id` hiện chỉ giữ 4096 ID gần nhất trong RAM của phiên control service.
  Legacy không có ID/hạn dùng, nên không thể phân biệt bản tin giống hệt được
  phát lại sau khi khởi động lại. Backend cần schema v2 và cơ chế lưu ID bền.
- Camera hiện chỉ trả `available=false`; chưa có driver/bitrate/frame-drop.
- OTA hiện chỉ trả trạng thái “not implemented”; chưa tải, ký, rollback hay
  flash firmware Pixhawk.
- Chưa có bridge đưa cảnh báo do Pi tạo vào ô Vehicle Messages của QGC.
- Test tự động không ARM và không mở Pixhawk. Luồng hai service cần chạy lại
  bằng HITL trước khi xem là đã kiểm chứng tích hợp; bay thật cần kiểm tra
  riêng sau HITL.
