# Hai service điều khiển UAV: web là luồng chính

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
| Control service | `pi/control/service.py` | Giữ MQTT, chỉ subscribe `control`, lọc retain/trùng payload trong phiên, ghi log/health cục bộ, chuyển lệnh qua IPC; **không import/call MAVSDK** |
| Flight service | `pi/flight/service.py` | Chủ duy nhất của MAVSDK/Pixhawk, gọi `GpsMissionControl`, trả status |
| Định tuyến lệnh | `pi/control/command_router.py`, `pi/flight/commands.py` | Chuyển GPS đã xác thực qua IPC; phía flight xử lý lệnh bay và lệnh giám sát cục bộ |
| Cấu hình | `pi/control/config_manager.py` | Lưu chu kỳ ghi trạng thái và health cục bộ đã được kiểm tra |
| Giao thức | `pi/control/protocol.py` | Chuyển payload sáu trường `control` thành một `gps_start` |
| Monitor MQTT | `pi/control/monitor.py` | Xem payload `control` chỉ đọc, không ra lệnh bay |
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
│   ├── command_router.py      # chuyển GPS đã kiểm tra sang Flight
│   ├── config_manager.py
│   └── monitor.py             # xem MQTT chỉ đọc
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

Luồng MQTT từ web chỉ hỗ trợ một nhiệm vụ `gps_start` thông qua topic
`control`. Các lệnh `pause`, `resume`, `cancel`, `return_home`,
`return_height`, `land` và `disarm` hiện chỉ có trong client giám sát cục
bộ qua IPC. Không có lệnh web `fly x y`.

Payload `control` hiện tại:

```text
c:spd:0.5;c:height:3;c:startlat:47.3977760;c:startlong:8.5456050;c:endlat:47.3978100;c:endlong:8.5456500;
```

Nó được hiểu nguyên tử là `gps_plan(...)` rồi `gps_start()`. Vì backend
không gửi `command_id`, Pi tạo ID theo payload và chặn khi ID đó còn trong
4096 ID gần nhất của phiên. Retain luôn bị bỏ qua.
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
  --flight-socket /tmp/uav-flight.sock
```

Sau đó nút “Gửi nhiệm vụ & cất cánh” trên web gửi sáu trường `control` và
control service gọi flight service. Service không publish topic nào dưới
`lac/uav01`; kiểm tra `status` bằng client cục bộ bên dưới. Xóa bản tin
retained cũ trên broker theo [hướng dẫn MQTT](WEB_GPS_MISSION.md).

Log nằm trong `session-logs/services/*.jsonl`. Mỗi dòng có thời gian UTC,
boot/session, service, severity, event, command/mission ID và dữ liệu có cấu
trúc. Log xoay file theo kích thước nhưng mặc định không tự xóa file cũ.
Để tạo một bảng CSV gồm thời gian, service, sự kiện, CPU/RAM/nhiệt độ,
phase và lệnh từ hai log gốc, dùng
`python3 pi/observability/export_logs.py --log-dir session-logs/services --output combined-review.csv --format csv`
từ thư mục `controller/`. File nguồn không bị thay đổi.

Web hiện chưa có các nút Pause/Resume/LAND. Giữ một terminal để mở
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

## Giới hạn đã biết

- Payload web có sáu trường nhưng không có ID hoặc hạn dùng. Service chặn
  bản tin giống hệt trong phiên hiện tại, không giữ danh sách đó sau reboot.
- Control Service không publish trạng thái hoặc xác nhận lên MQTT. Xem log
  JSONL, `flight/client.py status` và QGC để biết tiến độ.
- Unit test không ARM và không mở Pixhawk. Chưa có smoke test Web → MQTT →
  hai service → HITL trên đúng bộ PC/Pi/Pixhawk; bay thật cần kiểm tra riêng.
