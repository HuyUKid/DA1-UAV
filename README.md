# UAV — điều khiển bằng Raspberry Pi và Pixhawk

Repository công khai: [HuyUKid/DA1-UAV](https://github.com/HuyUKid/DA1-UAV).

Pi nhận lệnh console, gửi vị trí local NED qua MAVLink serial và giám sát
trạng thái chuyến bay. Pixhawk/PX4 chạy estimator và toàn bộ vòng điều
khiển vị trí, vận tốc, attitude, rate và motor.

**Mô phỏng HITL:** Pi nối UART với TELEM2 của Pixhawk; máy tính mô phỏng
nối USB với Pixhawk để trao đổi dữ liệu HIL.

```text
Pi/console ↔ UART ↔ TELEM2 Pixhawk/PX4 (SYS_HITL=1)
                              ↕ USB / MAVLink HIL
                       PC / Gazebo Classic X500
                              ↕ UDP
                       QGC / observer
```

**Bay thật theo cách đấu nối của bạn:** Pi nối USB với cổng Type-C của
Pixhawk; máy tính nối mạng với Pi và dùng UDP để trao đổi MAVLink.

```text
PC / QGroundControl ↔ UDP qua mạng ↔ Pi ↔ USB Type-C ↔ Pixhawk/PX4 → motor
PC / terminal       ↔ SSH         ↔ Pi/console
```

Đường UDP cần dịch vụ chuyển tiếp MAVLink trên Pi, cấu hình riêng ngoài
repository. Sơ đồ này mô tả cách kết nối thiết bị; xem giới hạn chia sẻ
cổng USB ở phần dưới trước khi chạy QGC và console cùng lúc.

## Cấu trúc dự án

```text
UAV/                              Gốc workspace/repository, không có uav/ lồng bên trong
├── README.md                     Hướng dẫn chính
├── AGENT.md                      Quy tắc làm việc và kiểm tra dự án
├── controller/                   Toàn bộ mã nguồn/công cụ phần điều khiển hiện tại
│   ├── pi/                       Console, FSM, MAVSDK, policy, validation, UART
│   ├── tests/                    Chỉ unit test Pi
│   ├── tools/                    Chẩn đoán Pi, build MAVSDK, phân tích ULog
│   └── params/hardware.params    Overlay ứng viên UAV thật, giới hạn bay chậm
├── simulation/                   Toàn bộ phần mô phỏng, có thể chép sang PC khác
│   ├── x500/                     Model/world và công cụ Gazebo Classic
│   ├── tests/                    Test model và smoke test HITL
│   ├── params/x500_hitl.params    HITL X500 và giới hạn bay chậm đã thử
│   ├── setup_classic.sh          Cài Classic 11, tải PX4 đã ghim và build plugin
│   ├── install_classic.sh        Cài dependency, dùng plugin có sẵn, không build
│   ├── prebuilt/                Plugin Classic cho Ubuntu 22.04 x86_64
│   ├── requirements.txt
│   └── docs/SETUP.md             Hướng dẫn cài và chạy trên PC mô phỏng
├── docs/                         Trạng thái bay và sơ đồ
└── logs/2026-10-24/               Bốn ULog, analysis.json và báo cáo ngày 24/10
```

`.venv/`, cache, session log và kết quả chạy được Git bỏ qua. Bốn ULog gốc
trong `logs/2026-10-24/` được đưa lên repository cùng báo cáo và
`analysis.json` để có thể tái phân tích trên máy khác. Các ULog phát sinh
ngoài thư mục này vẫn được bỏ qua mặc định.

## Cài mô phỏng trên PC sau khi clone

Trên **Ubuntu 22.04 x86_64**, tải dự án vào thư mục tên `UAV` rồi chạy:

```bash
git clone https://github.com/HuyUKid/DA1-UAV.git UAV
cd UAV
bash simulation/install_classic.sh
```

Bộ cài cần Internet và quyền `sudo` để cài Gazebo Classic 11 cùng runtime.
Nó tạo `simulation/.venv`, cài thư viện Python bằng wheel và kiểm tra
plugin/SDF. **Không tải source PX4, không chạy compiler và không build plugin.**
Git đã chứa model X500, mesh, world, công cụ chạy và 12 thư viện Classic
đã build (khoảng 3,3 MB) trong `simulation/prebuilt/ubuntu-22.04-x86_64/`.
Gazebo, QGroundControl, venv và firmware Pixhawk không được đóng gói vào Git.
QGroundControl tải riêng; firmware và tham số HITL cấu hình trên Pixhawk.
Không cần ROS 2 cho luồng này.

Nếu máy đã có Gazebo Classic 11 và Python venv, bỏ qua cài apt:

```bash
bash simulation/install_classic.sh --skip-system
```

Sau khi cấu hình Pixhawk HITL, nối USB và chuẩn bị Pi theo
[SETUP](simulation/docs/SETUP.md), mở simulator bằng:

```bash
simulation/.venv/bin/python simulation/x500/launch.py --serial auto
```

`auto` chỉ chọn khi có đúng một USB serial trong `/dev/serial/by-id/`;
có nhiều thiết bị thì truyền `--serial /dev/serial/by-id/THIET_BI`.
Launcher sửa cổng/baud trong bản model tạm, giữ nguyên model nguồn trong Git.
Bộ cài không tự flash firmware, cấu hình Pixhawk hoặc khởi chạy HITL.
HITL cần Pixhawk thật. Console có thể chạy trên Pi qua TELEM2 hoặc ngay
trên PC qua UDP loopback của Gazebo như bên dưới.
[PX4 Classic](https://docs.px4.io/v1.16/en/sim_gazebo_classic/).

Bộ binary dành riêng cho Ubuntu 22.04 x86_64/Classic 11. Với hệ điều hành
hoặc kiến trúc khác, dùng môi trường tương thích hoặc tự build và chỉ định
`--px4 PATH`. `simulation/setup_classic.sh` giữ lại quy trình tải/build
source trên Ubuntu 22.04 cho người bảo trì; không cần chạy khi dùng bộ
binary có sẵn. [Chi tiết bộ binary](simulation/prebuilt/ubuntu-22.04-x86_64/README.md).

## Kiểm tra bằng terminal ngay trên PC

Khi Gazebo đã nối USB Pixhawk ở HITL, không để console mở cùng USB.
Từ gốc dự án đầy đủ (có cả `controller/` và `simulation/`), cài MAVSDK trên PC:

```bash
simulation/.venv/bin/python -m pip install --only-binary=:all: -r controller/pi/requirements.txt
simulation/.venv/bin/python controller/pi/console.py --profile hitl \
  --connection udpin://127.0.0.1:14540 --check
```

Console dùng cùng FSM như trên Pi; chỉ đường truyền thay đổi:

```text
PC console ↔ UDP 127.0.0.1:14540 ↔ Gazebo Classic ↔ USB ↔ Pixhawk HITL
```

Chỉ một console/observer dùng UDP 14540; đóng observer trước khi mở console.
Không cần Pi cho cách kiểm tra này. Profile `hitl` vẫn kiểm tra `SYS_HITL=1`;
profile `hardware` tiếp tục yêu cầu serial, không nhận kết nối UDP.
Đã chạy bài bay HITL ngày 26/10: TAKEOFF/HOLD/FLY/LAND, LAND ưu tiên và mất luồng Offboard; xem [số đo và giới hạn](simulation/docs/ALGORITHM_VALIDATION_2026-10-26.md). Sau khi import file HITL, reboot, kiểm tra `SYS_HITL=1`, IDLE, DISARM, ON_GROUND, dữ liệu mới và preflight đạt:

```bash
simulation/.venv/bin/python controller/pi/console.py --profile hitl \
  --connection udpin://127.0.0.1:14540 --height 2 --enable-actuation
```

Nhập `status`, `takeoff`; chờ HOLD và `takeoff_complete=true`, rồi
`fly 1 2`; chờ HOLD, sau đó `land`. Chờ DISARM/ON_GROUND trước `exit` hoặc
đóng Gazebo. Không dùng `disarm` thay LAND vì lệnh đó force-stop motor.

## Cài code trên Pi

Nếu dùng một máy khác để SSH vào Pi và nhập lệnh trong console Pi qua TELEM2,
xem [quy trình HITL qua Pi](controller/docs/PI_HITL_REMOTE.md). Gói chuyển
nhanh cục bộ nằm ở `dist/uav-pi-hitl-20261026.tar.gz` (bị Git ignore);
chạy console trên Pi không cần UDP API từ máy điều khiển.

Từ gốc dự án trên PC, thay địa chỉ SSH bằng địa chỉ Pi thực tế:

```bash
ssh pi@<PI_IP> 'mkdir -p ~/uav/controller'
rsync -av --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='session-logs/' controller/ pi@<PI_IP>:~/uav/controller/
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

### HITL: Pi ↔ TELEM2, PC ↔ USB Pixhawk

Nối UART Pi với TELEM2: TX↔RX, RX↔TX, GND, đúng mức logic theo bo.
Cổng Linux/baud phải khớp cấu hình thực. Ví dụ hiện dùng
`serial:///dev/ttyAMA0:921600` và MAVLink instance 1 trên TELEM2.
USB Pixhawk nối PC chạy Gazebo, không nối Pi trong sơ đồ HITL này.
QGC nhận UDP từ simulator; quy trình đầy đủ ở
[hướng dẫn mô phỏng](simulation/docs/SETUP.md).

### Bay thật: Pi ↔ USB Type-C Pixhawk, PC ↔ UDP Pi

Dùng cáp USB truyền dữ liệu từ Pi tới cổng Type-C của Pixhawk. Trên Pi,
kiểm tra tên cổng sau khi cắm:

```bash
ls -l /dev/serial/by-id/
```

USB serial thường xuất hiện dưới tên `/dev/ttyACM0`; phải dùng tên thực
tế trên Pi, ưu tiên đường dẫn ổn định `/dev/serial/by-id/...` khi có.
Console hiện nhận URI `serial:///dev/DEVICE:BAUD`, nên có thể dùng USB
serial mà không đổi code. Các ví dụ bay thật bên dưới dùng
`serial:///dev/ttyACM0:921600`; đây không còn là UART GPIO `/dev/ttyAMA0`.

UDP là đường MAVLink giữa QGC trên PC và dịch vụ chuyển tiếp trên Pi,
chẳng hạn MAVLink Router. Dự án chưa kèm dịch vụ/cấu hình này và chưa
nhận các chuỗi lệnh `arm`, `fly`, `land` qua UDP. Để nhập những lệnh đó,
SSH vào Pi rồi chạy console. Tham khảo
[kiến trúc companion của PX4](https://docs.px4.io/main/en/companion_computer/index).

Chỉ một tiến trình được giữ cổng USB Pixhawk. Lệnh console nối trực tiếp
USB ở dưới dùng khi router không giữ cổng đó. Nếu router đang giữ USB để
phục vụ QGC qua UDP, không chạy thêm console mở cùng USB: cần cấu hình
router cấp một cổng serial ảo riêng cho console, hoặc bổ sung hỗ trợ
console kết nối router qua UDP. Repository hiện chưa triển khai hai cách
chia sẻ này cho profile `hardware`, vốn chỉ nhận serial. UDP loopback chỉ
được hỗ trợ cho HITL trên PC ở mục trên. Đường QGC qua UDP và console qua USB chưa được kiểm chứng
chạy đồng thời trong cấu hình này.

### Profile và phạm vi file tham số

| Môi trường | Profile console | `SYS_HITL` | File cấu hình tham khảo |
|---|---|---:|---|
| UAV thật, Pi nối USB | `hardware` | 0 | `controller/params/hardware.params`: có `SYS_HITL=0`, phần giao tiếp còn lại dành cho TELEM2, không phải USB |
| Gazebo HITL, Pixhawk thật | `hitl` | 1 | `simulation/params/x500_hitl.params` |

Hai file là overlay tham số một phần, không phải bản cấu hình đầy đủ của UAV. Kết quả bay và lý do chọn giá trị nằm ở [báo cáo HITL 26/10](simulation/docs/ALGORITHM_VALIDATION_2026-10-26.md).
Không import toàn bộ `hardware.params` với mục đích cấu hình USB: các
dòng MAVLink instance 1/TELEM2 trong file không cấu hình đường USB đang
dùng. Kiểm tra MAVLink USB trên firmware thực tế của Pixhawk trong QGC;
profile `hardware` chỉ kiểm tra `SYS_HITL=0`, không tự ghi tham số.
Với TX/RX/GND, `MAV_1_FLOW_CTRL=0` tắt RTS/CTS; `2` là auto-detect.
Sao lưu tham số, đối chiếu firmware/cổng/wiring trong QGC trước khi import
và reboot sau thay cấu hình serial/HITL. [Tham chiếu PX4](https://docs.px4.io/v1.17/en/advanced_config/parameter_reference#MAV_1_FLOW_CTRL).

Bộ HITL hiện dùng giới hạn XY 0,5 m/s, takeoff 0,4 m/s, LAND 0,3 m/s và hover 0,74 trên model X500. Bộ `hardware.params` chỉ chuyển các giới hạn chuyển động chậm thành **ứng viên** cho UAV thật; không chuyển hover/PID hoặc breaker HITL. File thật đặt `SYS_HITL=0`, airframe generic Quad-X 4001, clear HIL output, bật lại safety checks và đặt 6S. Khi quay về bay thật phải khôi phục/kiểm tra output, calibration, RC, battery scaling, failsafe trên chính UAV trong QGC rồi thử nghiệm từng bước. Chưa nạp hoặc kiểm chứng file thật trên thiết bị.
Bỏ dòng khỏi file overlay không xóa giá trị đã được nạp trước đó trên Pixhawk.
[Đánh giá hai file cũ](logs/2026-10-24/BAO_CAO_2026-10-24.md#12-rà-soát-hai-file-tham-số-được-bổ-sung).

## Chạy console

Các lệnh trong phần này chạy trên Pi từ `~/uav/controller`, trực tiếp
hoặc qua SSH từ PC. Ví dụ cho bay thật, Pi đang giữ trực tiếp cổng USB
Pixhawk và không có router/tiến trình khác giữ cổng đó:

```bash
.venv/bin/python pi/console.py --profile hardware \
  --connection serial:///dev/ttyACM0:921600 --check
```

Thay `/dev/ttyACM0` bằng thiết bị USB thực tế. Với HITL, dùng
`--profile hitl --connection serial:///dev/ttyAMA0:921600` vì Pi nối
TELEM2, còn USB Pixhawk do PC mô phỏng sử dụng.

`--check` chỉ đọc trạng thái. Trước ARM cần kết nối tốt, IDLE, disarmed,
ON_GROUND, telemetry mới, health/preflight đạt và không có termination.
X/y/z khác 0 không tự nó là lỗi GPS: đây là gốc estimator trên Pixhawk.
Bốn log cũ có lỗi cảm biến và mất Offboard; đọc báo cáo trước khi bay lại.

Khi đã chuẩn bị đúng thiết bị và môi trường, bật quyền điều khiển:

```bash
.venv/bin/python pi/console.py --profile hardware \
  --connection serial:///dev/ttyACM0:921600 \
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

Các test Pi và model/công cụ mô phỏng không
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
