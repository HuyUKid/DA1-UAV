# UAV — điều khiển nhiệm vụ GPS

Điều khiển Pixhawk/PX4 bằng Python trên Raspberry Pi hoặc máy mô phỏng.
Web gửi nhiệm vụ GPS nhiều điểm qua MQTT; terminal kỹ thuật dùng cùng
Flight Service để kiểm tra NED/GPS. PX4 chạy estimator và các vòng điều
khiển bay; Pi quản lý trình tự lệnh và kiểm tra telemetry.

```text
Web → MQTT → Control Service → Unix socket → Flight Service → MAVSDK → PX4
Terminal flight/client.py ──────────┘
```

Repository: [HuyUKid/DA1-UAV](https://github.com/HuyUKid/DA1-UAV).

## Cấu trúc đang dùng

| Thư mục | Nội dung |
|---|---|
| `controller/pi/flight/` | Kết nối Pixhawk, FSM, Mission GPS, terminal IPC |
| `controller/pi/control/` | Nhận và kiểm tra lệnh MQTT |
| `controller/pi/ipc/` | Unix socket giữa các tiến trình |
| `controller/pi/observability/` | Hiển thị status, log, metrics và xuất file |
| `controller/params/` | Overlay tham số UAV thật |
| `controller/tests/`, `controller/tools/` | Test và công cụ triển khai/chẩn đoán |
| `controller/systemd/` | Mẫu chạy hai service trên Pi |
| `simulation/` | Model X500, bộ cài Classic HITL, tham số và test mô phỏng |
| `docs/` | FSM và sơ đồ thuật toán |
| `logs/` | Dữ liệu và báo cáo kiểm chứng theo ngày |

## Thông số vận hành

- TAKEOFF mặc định 2 m trên mốc local NED được chụp trước cất cánh.
- Nhiệm vụ GPS: tối đa 50 waypoint theo thứ tự, HOLD tại điểm cuối.
- Tốc độ ngang tối đa trong hai overlay: 1 m/s. Tốc độ từng nhiệm vụ do
  web/terminal chọn, không vượt giới hạn Pi và PX4.
- Pin: PX4 cảnh báo 30%, Pi cảnh báo thêm 15%, PX4 LAND ở critical 7%,
  emergency 5% sau khi nạp và đọc lại tham số trên bo.
- `status` giữ NED, GPS position, các mốc độ cao, vận tốc, health và pin;
  `status --json` xuất dữ liệu đầy đủ.

Các thay đổi nhiều waypoint, ARM/TAKEOFF web, tốc độ 1 m/s, pin và log mới
đã có kiểm thử phần mềm. Cấu hình hiện tại chưa được bay HITL/bay thật
trong phiên rà soát này. Các báo cáo trước nằm trong `logs/` và
`simulation/docs/`; kết quả cũ không xác nhận bản mã mới.

## Chọn hướng dẫn

| Công việc | Tài liệu |
|---|---|
| Cài mô phỏng, chạy PC hoặc Pi qua TELEM2 | [SETUP.md](simulation/docs/SETUP.md) |
| Setup Pi/USB/QGC, chạy service, tốc độ và pin | [HARDWARE_SETUP.md](controller/docs/HARDWARE_SETUP.md) |
| Thuật toán GPS, waypoint, payload và nút web | [GPS_MISSION_FLOW.md](controller/docs/GPS_MISSION_FLOW.md) |
| Status, log, mốc độ cao và tích hợp web | [LOGGING.md](controller/docs/LOGGING.md) |
| FSM và điều kiện local NED | [FLIGHT_STATES.md](docs/FLIGHT_STATES.md) |

## Thử trên PC mô phỏng

Từ gốc repository, cài simulator theo SETUP rồi mở Gazebo ở terminal 1:

```bash
PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
simulation/.venv/bin/python simulation/x500/launch.py --serial auto
```

Gazebo giữ USB Pixhawk. Terminal 2 mở Flight Service khi đã xác nhận
profile HITL, DISARM/ON_GROUND và tháo cánh:

```bash
simulation/.venv/bin/python controller/pi/flight/service.py \
  --profile hitl --connection udpin://127.0.0.1:14540 \
  --height 2 --gps-max-height 7 --gps-max-speed 1 \
  --socket /tmp/uav-flight.sock --enable-actuation
```

Terminal 3 mở client để kiểm tra và ra lệnh:

```bash
simulation/.venv/bin/python controller/pi/flight/client.py
```

Nếu dùng web, mở thêm Control Service; mật khẩu được hỏi tại prompt:

```bash
simulation/.venv/bin/python controller/pi/control/service.py \
  --device-id uav01 --username MQTT_USER --flight-socket /tmp/uav-flight.sock
```

`--enable-actuation` cho phép gửi lệnh bay; bỏ cờ khi chỉ đọc. Một tiến
trình duy nhất giữ cổng 14540. `console.py` là công cụ kết nối trực tiếp,
không chạy song song Flight Service trên cùng cổng.

## Lệnh terminal

| Lệnh | Chức năng |
|---|---|
| `status`, `status --json` | Xem tóm tắt hoặc đầy đủ |
| `arm` | ARM trên mặt đất |
| `takeoff` | Lên độ cao `--height`, rồi HOLD |
| `fly x y` | Tới tọa độ local NED tuyệt đối; giữ độ cao đích hiện có |
| `gps-plan A_lat A_lon B_lat B_lon height speed` | Lưu kế hoạch GPS hai điểm |
| `gps-start` | Triển khai kế hoạch đã lưu |
| `pause`, `resume`, `cancel` | Tạm dừng, tiếp tục hoặc hủy đích đang chạy |
| `return-home` | Về GPS cất cánh ở độ cao hiện tại, rồi HOLD |
| `return-height` | Giữ x/y hiện tại, về độ cao TAKEOFF |
| `land` | Yêu cầu hạ cánh |
| `disarm` | Force motor stop; UAV có thể rơi nếu đang trên không |
| `help`, `exit` | Trợ giúp hoặc đóng client |

Chờ xác nhận HOLD trước đích mới. Sau LAND, chờ ON_GROUND và armed=false.
Đóng client không tự LAND. Nhiệm vụ nhiều điểm dùng payload web/MQTT;
terminal `gps-plan` giữ cú pháp hai điểm.

Web/backend và bộ phát telemetry được triển khai riêng. Trong hệ thống
hiện tại, reader trên Pi nhận bản sao MAVLink ở 14541 để gửi trạng thái
lên web. Hợp đồng lệnh và telemetry được ghi trong hướng dẫn GPS và log; mã backend/gateway không nằm trong repository này.

## Kiểm thử

```bash
python3 -B -m unittest discover -s controller/tests -p 'test_*.py'
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
```

Unit test dùng mock và không điều khiển motor. Kiểm tra tĩnh không thay
thế bài bay HITL. Nạp file `.params` là thao tác riêng trên Pixhawk;
sửa file trong repository không thay tham số đang chạy trên bo.
