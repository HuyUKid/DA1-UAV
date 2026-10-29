# UAV — điều khiển nhiệm vụ GPS qua web

Repository: [HuyUKid/DA1-UAV](https://github.com/HuyUKid/DA1-UAV).

Luồng sản phẩm là web gửi nhiệm vụ GPS A→B qua MQTT. Một service trên
Raspberry Pi giữ kết nối với broker, kiểm tra bản tin và gửi ACK/trạng thái;
service bay riêng là tiến trình duy nhất nói chuyện với Pixhawk qua MAVSDK.
Pixhawk/PX4 chạy estimator và các vòng điều khiển bay. `fly x y` trong
terminal là công cụ thử local NED, không phải lệnh web.

```text
Web/backend → MQTT broker → control service → Unix socket → flight service → Pixhawk/PX4
                                │                                │
                           health + ACK                    GPS A→B + FSM
                                └──────── log JSONL trên PC/Pi ────────┘
```

## Phạm vi hiện tại

Code hai service đã có cùng unit test bằng mock. Luồng mới **chưa được thử
end to end** bằng Web → MQTT → hai service → Gazebo HITL → Pixhawk và chưa
bay thật. Bài HITL GPS trước đây dùng console riêng; không coi đó là bằng
chứng cho service mới. Đừng bật service bay thật chỉ dựa trên unit test.

| Thành phần | Đường dẫn |
|---|---|
| MQTT, lọc bản tin, ACK, cấu hình và sức khỏe | [`controller/pi/control/`](controller/pi/control/) |
| Điều khiển GPS/FSM, một chủ MAVSDK | [`controller/pi/flight/`](controller/pi/flight/), [`gps_mission.py`](controller/pi/flight/gps_mission.py) |
| Giao tiếp nội bộ và log | [`controller/pi/ipc/`](controller/pi/ipc/), [`observability/`](controller/pi/observability/) |
| Tham số Pixhawk | [`simulation/params/x500_hitl.params`](simulation/params/x500_hitl.params), [`controller/params/hardware.params`](controller/params/hardware.params) |
| Mô phỏng Gazebo Classic X500 | [`simulation/`](simulation/) |
| Console kỹ thuật local NED | [`controller/pi/console.py`](controller/pi/console.py) |

Chi tiết chức năng và các phần chưa hoàn thành: [PI_SERVICES.md](controller/docs/PI_SERVICES.md).
Trạng thái thuật toán GPS: [WEB_GPS_MISSION.md](controller/docs/WEB_GPS_MISSION.md).

## Cài và mở mô phỏng HITL trên PC

Máy mô phỏng cần Ubuntu 22.04 x86_64, Pixhawk thật đã cấu hình `SYS_HITL=1`,
Gazebo Classic 11 và các dependency của bộ cài. Repository đã chứa model,
world, mesh/texture và plugin Classic build sẵn cho nền tảng đó. PX4 source,
QGroundControl, Python venv và firmware Pixhawk không đi kèm. Không cần ROS 2.

```bash
git clone https://github.com/HuyUKid/DA1-UAV.git UAV
cd UAV
bash simulation/install_classic.sh
simulation/.venv/bin/python -m pip install --only-binary=:all: \
  -r controller/pi/flight/requirements.txt -r controller/pi/control/requirements.txt
```

Nếu Gazebo Classic 11 đã cài: `bash simulation/install_classic.sh --skip-system`.
Nếu dùng nền tảng khác, xem [SETUP.md](simulation/docs/SETUP.md); gói plugin
có sẵn không dùng chung cho mọi hệ điều hành. Bộ cài không flash firmware,
không nạp tham số Pixhawk.

Trước thử HITL: tháo cánh; trong QGC xác nhận `SYS_HITL=1`, DISARM,
ON_GROUND và các tham số HITL tương ứng model X500. Mở Gazebo ở terminal 1:

```bash
PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
simulation/.venv/bin/python simulation/x500/launch.py --serial auto
```

`--serial auto` chỉ phù hợp khi có đúng một USB serial Pixhawk. Gazebo giữ
USB; flight service kết nối UDP loopback 14540. Không chạy đồng thời console,
observer hoặc flight service thứ hai trên cùng cổng đó.

## Chạy hai service để thử web trong HITL

Trong terminal 2 tại gốc repository, mở flight service. Khi chỉ kiểm tra
trạng thái, bỏ `--enable-actuation`; chỉ thêm cờ này trong buổi thử HITL
có giám sát trực tiếp và đã xác nhận bo đang DISARM:

```bash
simulation/.venv/bin/python controller/pi/flight/service.py \
  --profile hitl --connection udpin://127.0.0.1:14540 \
  --height 2.5 --gps-max-height 3 --gps-max-speed 0.5 \
  --socket /tmp/uav-flight.sock --enable-actuation
```

Trong terminal 3, mở control service (thay `MQTT_USER` bằng tài khoản broker;
mật khẩu được hỏi kín, không đặt trong command line):

```bash
simulation/.venv/bin/python controller/pi/control/service.py \
  --device-id uav01 --username MQTT_USER \
  --flight-socket /tmp/uav-flight.sock --allow-legacy-start
```

`--allow-legacy-start` chỉ dành cho nút web hiện gửi sáu trường trong **một**
payload `c:...;`. Retain phải OFF. Bỏ cờ này khi backend gửi lệnh JSON v2
có `command_id` và hạn dùng. Control service công bố:

- `lac/uav01/v2/ack`: đã nhận/chấp nhận/từ chối lệnh, chưa phải đã tới đích.
- `lac/uav01/v2/state`: trạng thái hiện tại do Pixhawk/flight service báo.
- `lac/uav01/v2/health`, `/event` và `/availability`: sức khỏe Pi, thay đổi
  trạng thái và kết nối.

Web hiện tại chưa chắc đã đọc các topic v2; nếu giao diện vẫn báo mất kết
nối, xem MQTT Explorer và file `session-logs/services/*.jsonl`. Một payload
legacy giống hệt bị chặn khi ID của nó còn trong 4096 ID gần nhất; sau
restart chưa có chống phát lại bền. Web legacy hiện chưa có các nút
Pause/Resume/LAND được xác minh. Mở console giám sát cục bộ qua cùng flight
service ở terminal khác:

```bash
simulation/.venv/bin/python controller/pi/flight/client.py
```

Tại `UAV-REMOTE>` dùng `status`, `pause`, `resume`, `cancel`, `return-home`,
`return-height` hoặc `land`. `disarm` gửi dừng motor khẩn cấp ngay, không có
bước xác nhận thứ hai và có thể làm UAV rơi; không dùng thay LAND. `exit`/Ctrl+C không tự LAND. ACK không phải xác
nhận đã chạm đất; đợi ON_GROUND và DISARM trong `status`/QGC rồi mới dừng
service và Gazebo.

## Triển khai Raspberry Pi

Trong HITL, PC mô phỏng nối USB Pixhawk, Pi có thể nối TELEM2 bằng UART.
Bay thật, Pi có thể nối Pixhawk bằng USB và MAVLink Router chia cổng cho
flight service và QGC. Profile `hitl` yêu cầu `SYS_HITL=1`; profile
`hardware` yêu cầu `SYS_HITL=0`. Cả hai file `.params` chỉ là overlay một
phần. File `hardware.params` là ứng viên, chưa được kiểm chứng trên UAV
thật; không sao chép tuning hover/PID của X500 sang UAV 5–6 kg.

Hướng dẫn dây/cổng và kiểm tra trên đất: [PI_HITL_REMOTE.md](controller/docs/PI_HITL_REMOTE.md),
[HARDWARE_SETUP.md](controller/docs/HARDWARE_SETUP.md). Mẫu systemd ở
[`controller/systemd/`](controller/systemd/) mặc định mở flight service
**chỉ đọc**; sau khi kiểm chứng mới cấu hình quyền điều khiển. `control`
service cần vẫn giữ MQTT và báo lỗi nếu flight service tạm ngừng.

## Nhật ký và kiểm thử

Hai service lưu JSONL theo phiên trong thư mục `--log-dir`. PX4 ULog trên
thẻ SD, QGC Messages và log Pi là ba nguồn khác nhau. Bản hiện tại chưa
thu đủ pin/GPS/status text Pixhawk, chưa gộp thành một file cho mỗi chuyến
bay, chưa có camera hoặc OTA. Xem [thiết kế quan sát](controller/docs/MQTT_OBSERVABILITY_DESIGN.md).

```bash
python3 -B -m unittest discover -s controller/tests -p 'test_*.py'
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
```

Các bài này không ARM hoặc mở phiên bay. Báo cáo HITL cũ và dữ liệu gốc
nằm tại [ALGORITHM_VALIDATION_2026-10-26.md](simulation/docs/ALGORITHM_VALIDATION_2026-10-26.md)
và `logs/2026-10-24/`; đó là bằng chứng lịch sử của phiên console/model,
không thay thế smoke test hai service hiện tại.
