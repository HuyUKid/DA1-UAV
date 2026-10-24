# Đồ án 1 — điều khiển UAV bằng Raspberry Pi và Pixhawk

Repository công khai: [HuyUKid/DA1-UAV](https://github.com/HuyUKid/DA1-UAV).

Pi nhận lệnh console, gửi vị trí local NED qua MAVLink UART và giám sát
trạng thái chuyến bay. Pixhawk/PX4 chạy estimator và toàn bộ vòng điều
khiển vị trí, vận tốc, attitude, rate và motor.

```text
Người vận hành → Pi/console → UART/TELEM2 → Pixhawk/PX4 → motor
                                              ↕ USB, khi dùng HITL
                                       PC khác/Gazebo Classic X500
```

## Cấu trúc dự án

```text
UAV/                              Gốc workspace/repository, không có uav/ lồng bên trong
├── README.md                     Hướng dẫn chính
├── AGENT.md                      Quy tắc làm việc và kiểm tra dự án
├── controller/                   Toàn bộ mã nguồn/công cụ phần điều khiển hiện tại
│   ├── pi/                       Console, FSM, MAVSDK, policy, validation, UART
│   ├── tests/                    Chỉ unit test Pi
│   ├── tools/                    Chẩn đoán Pi, build MAVSDK, phân tích ULog
│   └── params/hardware.params    Cấu hình giao tiếp cho UAV thật
├── simulation/                   Toàn bộ phần mô phỏng, có thể chép sang PC khác
│   ├── x500/                     Model/world và công cụ Gazebo Classic
│   ├── tests/                    Test model và smoke test HITL
│   ├── params/x500_hitl.params    Cấu hình HITL/giao tiếp, không có tuning bay cũ
│   ├── requirements.txt
│   └── docs/SETUP.md             Hướng dẫn cài và chạy trên PC mô phỏng
├── docs/                         Trạng thái bay và sơ đồ
└── logs/2026-10-24/               Bốn ULog, analysis.json và báo cáo ngày 24/10
```

`.venv/`, cache, session log và kết quả chạy được Git bỏ qua. Bốn ULog gốc
trong `logs/2026-10-24/` được đưa lên repository cùng báo cáo và
`analysis.json` để có thể tái phân tích trên máy khác. Các ULog phát sinh
ngoài thư mục này vẫn được bỏ qua mặc định.

## Cài code trên Pi

Từ gốc dự án trên PC, thay địa chỉ SSH bằng địa chỉ Pi thực tế:

```bash
ssh pi@192.168.50.1 'mkdir -p ~/uav/controller'
rsync -av --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='session-logs/' controller/ pi@192.168.50.1:~/uav/controller/
```

Trên Pi:

```bash
cd ~/uav/controller
python3 -m venv .venv
.venv/bin/python -m pip install -r pi/requirements.txt
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

MAVSDK được ghim `4.0.6`. Tạo venv trên từng máy/đúng đường dẫn; venv cũ
cần tạo lại nếu đã di chuyển thư mục. Sau mỗi lần cập nhật, chỉ đồng bộ
khi UAV đã disarm và phiên console đã dừng. Nếu cần xử lý lỗi native trên
Pi ARM64, xem [build MAVSDK](docs/FLIGHT_STATES.md#native-mavsdk-trên-pi).

## Kết nối và tham số

Nối UART Pi với TELEM2: TX↔RX, RX↔TX, GND, đúng mức logic theo bo.
Cổng Linux/baud phải khớp cấu hình thực, chỉ một tiến trình giữ cổng.
Ví dụ hiện dùng `/dev/ttyAMA0:921600` và MAVLink instance 1 trên TELEM2.

| Môi trường | Profile console | `SYS_HITL` | File cấu hình tham khảo |
|---|---|---:|---|
| UAV thật | `hardware` | 0 | `controller/params/hardware.params` |
| Gazebo HITL, Pixhawk thật | `hitl` | 1 | `simulation/params/x500_hitl.params` |

Hai file là overlay tối thiểu, không phải bản cấu hình đầy đủ của UAV.
Với TX/RX/GND, `MAV_1_FLOW_CTRL=0` tắt RTS/CTS; `2` là auto-detect.
Sao lưu tham số, đối chiếu firmware/cổng/wiring trong QGC trước khi import
và reboot sau thay cấu hình serial/HITL. [Tham chiếu PX4](https://docs.px4.io/v1.17/en/advanced_config/parameter_reference#MAV_1_FLOW_CTRL).

Các giá trị tuning cũ chưa có log xác thực tương ứng nên đã loại khỏi
file nạp; các dòng failsafe cũng được bỏ để cấu hình riêng trong QGC.
Cấu hình airframe, actuator, calibration, RC, pin và failsafe trên chính
thiết bị trong QGC; cần kiểm chứng tham số bay lại bằng log mới.
`hardware.params` không phục hồi airframe/output sau HITL: khi quay về bay
thật phải khôi phục và kiểm tra bộ cấu hình UAV thật đã sao lưu. Bỏ dòng
khỏi file overlay không xóa giá trị đã được nạp trước đó trên Pixhawk.
[Đánh giá hai file cũ](logs/2026-10-24/BAO_CAO_2026-10-24.md#12-rà-soát-hai-file-tham-số-được-bổ-sung).

## Chạy console

Các lệnh trong phần này chạy trên Pi từ `~/uav/controller`:

```bash
.venv/bin/python pi/console.py --profile hardware \
  --connection serial:///dev/ttyAMA0:921600 --check
```

`--check` chỉ đọc trạng thái. Trước ARM cần kết nối tốt, IDLE, disarmed,
ON_GROUND, telemetry mới, health/preflight đạt và không có termination.
X/y/z khác 0 không tự nó là lỗi GPS: đây là gốc estimator trên Pixhawk.
Bốn log cũ có lỗi cảm biến và mất Offboard; đọc báo cáo trước khi bay lại.

Khi đã chuẩn bị đúng thiết bị và môi trường, bật quyền điều khiển:

```bash
.venv/bin/python pi/console.py --profile hardware \
  --connection serial:///dev/ttyAMA0:921600 \
  --height 2 --xy-tolerance 0.5 --z-tolerance 0.3 \
  --yaw-tolerance 10 --settle-time 2 --target-timeout 60 \
  --enable-actuation
```

| Lệnh | Hành vi |
|---|---|
| `arm` | ARM trên đất, không yêu cầu cất cánh; motor có thể quay |
| `takeoff` | Giữ x/y, lên `height` mét từ mốc z lúc TAKEOFF; tự ARM nếu bắt đầu từ IDLE |
| `fly x y` | Rời HOLD, tới đích Bắc/Đông tuyệt đối theo gốc EKF, đơn vị mét |
| `fly`, rồi `x y` | Chọn nhận tọa độ rồi gửi đích |
| `land` | Yêu cầu PX4 hạ cánh có điều khiển, giữ kết nối |
| `disarm` | Dừng motor cưỡng bức trên đất hoặc trên không; có thể làm UAV rơi |
| `status` / `help` | Đọc trạng thái / cú pháp |
| `exit` | Đóng phiên, ngừng stream; hạ cánh và xác nhận disarm trước khi thoát |

Luồng: `IDLE → ARMED → TAKEOFF → SETTLING → HOLD → FLY → SETTLING → HOLD`.
ARM riêng là tùy chọn. TAKEOFF/FLY khóa đích, LAND/DISARM đi qua khóa khi
console xử lý lệnh. HOLD tự động, giữ tới lệnh tiếp theo. Mặc định sai số
ngang 0,5 m, z 0,3 m, yaw 10°, ổn định 2 s; 2 s dùng xác nhận tới đích,
không phải thời gian tự kết thúc HOLD.

LAND/DISARM chỉ trả IDLE khi telemetry mới có `armed=false` và ON_GROUND.
Sau đó có thể ARM hoặc TAKEOFF lại nếu PX4 cho phép. ACK khác xác nhận
trạng thái. Sơ đồ đầy đủ, timeout, status và tham số nằm trong
[FLIGHT_STATES.md](docs/FLIGHT_STATES.md); kiến trúc đã gộp vào README này.

## Kiểm thử và chẩn đoán

Từ gốc repository:

```bash
python3 -B -m unittest discover -s controller/tests -p 'test_*.py'
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
```

Hiện có 71 test Pi và 19 test model/công cụ mô phỏng. Các bài này không
mở UART, không gửi lệnh motor và không cần cài Gazebo. Smoke test HITL là
bài riêng trong hướng dẫn mô phỏng, không chạy qua unittest discover.

Thử trên bàn khi đã tháo cánh: `status → arm → status → disarm → status`.
`arm → land` là bài riêng, không chứng minh LAND sau TAKEOFF đã hết lỗi.
Console lưu `session-logs/pi-*.log` và `.fault.log` tại thư mục chạy.

Trên Pi, từ thư mục `controller`, ghi chẩn đoán trước/sau sự cố khi UAV an toàn:

```bash
python3 tools/diagnose_pi.py > pi-before.json
python3 tools/diagnose_pi.py > pi-after.json
```

Phân tích bốn ULog từ gốc repository, dùng Python có numpy/pyulog:

```bash
controller/.venv/bin/python -m pip install -r controller/tools/requirements.txt
controller/.venv/bin/python controller/tools/analyze_logs.py \
  --log-dir logs/2026-10-24 --output logs/2026-10-24/analysis.json
```

## Tài liệu

- [Hướng dẫn cho người/agent sửa dự án](AGENT.md)
- [Báo cáo đầy đủ các lỗi và hướng xử lý](logs/2026-10-24/BAO_CAO_2026-10-24.md)
- [Trạng thái bay, tham số và quy trình kiểm chứng](docs/FLIGHT_STATES.md)
- [Cài/chạy mô phỏng trên PC khác](simulation/docs/SETUP.md)
- [Sơ đồ draw.io](docs/UAV_diagram.drawio), [sequence](docs/UAV_sequence_diagram.txt)
