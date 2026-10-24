# Mô phỏng X500 với Gazebo Classic HITL

## Kết quả kiểm tra hiện tại

Ngày 24/10/2026, máy workspace là Ubuntu 26.04, chưa có `gazebo`,
`gzserver`, `gz` hoặc PX4 source/plugin build. Vì vậy kết quả hiện tại là
**đã kiểm tra tĩnh model và công cụ, chưa chạy Gazebo/HITL hoặc bay mô phỏng**.

| Hạng mục | Kết quả |
|---|---|
| XML model/world và tài nguyên mesh/texture | Kiểm tra đạt |
| Khối lượng, quán tính và hình học X500 | Giữ theo model nguồn đã lưu; tổng khối lượng link khoảng 2,0893 kg |
| Bốn motor, thứ tự, vị trí, chiều quay và hằng số | Kiểm tra tĩnh đạt; chưa kiểm chứng lực đẩy trong runtime |
| Sensor/bridge | Có IMU, GPS, magnetometer, barometer và MAVLink HIL plugin Classic |
| World | Nền phẳng 100×100 m, ánh sáng local, gravity −9,8066 m/s², bước 0,004 s / 250 Hz |
| Phụ thuộc tải model qua mạng | Nền và ánh sáng đã được đưa trực tiếp vào world |
| Môi trường chạy trên máy hiện tại | Chưa cài; thiếu binary và plugin |
| USB ↔ HIL, estimator đứng yên, TAKEOFF/HOLD/FLY/LAND | Chưa xác thực |

Có 19 test tại `simulation/tests/test_model.py` và
`simulation/tests/test_observation.py`: 12 test model/công cụ, 7 test tiêu
chí chấp nhận quan sát. Test đối chiếu body/inertial với bản X500 nguồn được lưu trong `generated/models/x500_base`.
Đây không phải phép đo mô hình đúng với khối lượng, cánh, motor và tải Pi
trên UAV của bạn. `generated/provenance.json` lưu revision/hash nguồn,
khối lượng và cách ánh xạ noise IMU; đường dẫn máy cũ trong metadata là
lịch sử tạo model, không phải đường dẫn mà launcher sẽ sử dụng.

## Bộ mô phỏng đang có

```text
Pi chạy console → TELEM2 → Pixhawk chạy PX4 ở HITL
                              ↕ USB / HIL_SENSOR / HIL_ACTUATOR_CONTROLS
                         PC chạy Gazebo Classic 11
                              ↕ UDP
                         QGroundControl / observer
```

Đây là model X500 port sang **Gazebo Classic**, dùng MAVLink HIL bridge.
Tên model bên trong SDF là `x500_hitl`, mã mô phỏng ở `simulation/x500/`
ngay dưới gốc repository. Tên model dùng cho URI và `gz model`.

### Vì sao bộ này chọn Classic?

SITL/HITL chỉ nơi PX4 chạy: PC hay flight controller thật. Gazebo và
Gazebo Classic là hai thế hệ simulator, không đồng nghĩa SITL và HITL.
PX4 v1.17 mô tả HITL cho multicopter bằng Classic hoặc jMAVSim; vì vậy
HITL không bắt buộc chỉ có Classic. Bộ dự án này chọn Classic để dùng
plugin MAVLink HIL sẵn có qua USB với Pixhawk. Đường `gz_x500` của Gazebo
mới được PX4 hướng dẫn cho SITL; đổi simulator mà giữ model/plugin hiện
tại không tự tạo được kết nối HITL tương đương.
[PX4 HITL](https://docs.px4.io/v1.17/en/simulation/hitl),
[PX4 Gazebo SITL](https://docs.px4.io/v1.17/en/sim_gazebo_gz/).

### Nguồn X500 và mức độ giữ nguyên khi chuyển

Đã đối chiếu trực tiếp ngày 24/10/2026 với revision
`e05f4312d3f28aa621157610584a4870406cb6d3` của PX4-gazebo-models.
SHA-256 của `x500_base/model.sdf` và `x500/model.sdf` upstream khớp với
hai hash ghi trong provenance; bản `x500_base` lưu cục bộ khớp nguyên byte.
Đây là X500 dùng cho đường `gz_x500`, được port để chạy Classic.

| Phần | Kết quả đối chiếu |
|---|---|
| Link pose, quán tính, collision, joint của X500 gốc | Giữ nguyên cấu trúc |
| Motor 0–3, chiều quay, hằng số lực/moment, time constant | Giữ các giá trị nguồn; đổi plugin sang Classic |
| Mesh/texture | Giữ tài nguyên X500; bỏ PBR không tương thích Classic |
| Sensor và cầu nối Pixhawk | Dùng sensor/plugin/HIL transport của Classic, chuyển cấu hình từ `iris_hitl` |
| Khối lượng tổng | X500 nguồn khoảng 2,0643 kg; bản port khoảng 2,0893 kg, thêm IMU 15 g và GPS 10 g |
| Noise và động lực học khi chạy | Không được coi là giống hệt Gazebo mới; cần kiểm chứng runtime |

Đã tái tạo model trong thư mục tạm từ hai file X500 upstream và
`iris_hitl.sdf` tại Classic revision
`70683dc759cbd3ebccfa78429b564f8b1fb5d149` bằng `prepare.py` hiện tại:
XML model kết quả giống cấu trúc bản đang lưu. Không chạy simulator hoặc
thay model đang dùng trong quá trình đối chiếu này.

Hash file `iris_hitl.sdf` ghi từ lần tạo cũ khác hash upstream tại revision
đó. Giữ lại thông tin lịch sử, ghi kết quả đối chiếu riêng trong
`generated/provenance.json`; chưa xác định khác biệt file nguồn cũ do đâu.
Việc tái tạo model giống nhau xác nhận recipe hiện tại tái tạo được phần
model đang dùng, không chứng minh file nguồn Classic cũ giống nguyên byte.

Vì vậy có thể xác nhận đúng nguồn X500 SITL và phần cơ học được giữ khi
port. Chưa xác nhận tương đương toàn bộ mô phỏng hoặc đúng với khối lượng,
motor/cánh và tải trên UAV thật; cần đo/kiểm chứng riêng trước tuning.
[X500 upstream](https://github.com/PX4/PX4-gazebo-models/blob/e05f4312d3f28aa621157610584a4870406cb6d3/models/x500/model.sdf),
[X500 base upstream](https://github.com/PX4/PX4-gazebo-models/blob/e05f4312d3f28aa621157610584a4870406cb6d3/models/x500_base/model.sdf).

Gazebo Classic hết vòng đời từ tháng 1/2025. Hướng dẫn PX4 v1.16 dành
Classic cho Ubuntu 22.04; script cài PX4 mặc định hiện hướng tới Gazebo
mới. Hai bộ plugin không thay thế cho nhau. Với bộ model hiện có, dùng
một máy/môi trường Ubuntu 22.04 riêng, có GUI và USB passthrough nếu là
máy ảo. Chưa xác thực cài Classic trực tiếp trên Ubuntu 26.04.
[Nguồn Gazebo](https://classic.gazebosim.org/),
[PX4 Classic và môi trường Ubuntu](https://docs.px4.io/v1.16/en/sim_gazebo_classic/).

## Chạy trên một PC khác

PC mô phỏng không cần là máy đang mở IDE. Chép riêng `simulation/` sang
máy đó trong một thư mục làm việc, hoặc clone repository và chạy các
lệnh dưới đây tại gốc clone. Ví dụ khi chép riêng:

```bash
ssh USER_PC@DIA_CHI_PC 'mkdir -p ~/uav/simulation'
rsync -av --exclude='.venv/' --exclude='__pycache__/' --exclude='artifacts/' \
  simulation/ USER_PC@DIA_CHI_PC:~/uav/simulation/
```

Trên PC đó, `cd ~/uav` trước khi chạy các lệnh cài/kiểm tra.
PC cần Gazebo Classic/plugin/Python observer và USB nối Pixhawk. Pi vẫn
chạy `controller/pi/console.py` qua TELEM2 như
[README chính](../../README.md), không chạy code điều khiển bay trên PC.
QGC có thể chạy trên PC mô phỏng qua UDP loopback. Nếu đặt QGC ở máy
khác, cấu hình địa chỉ forwarding/firewall theo mạng thực; model đang
forward về `127.0.0.1` nên chưa tự chuyển tới IP máy QGC bên ngoài.

Khi kết thúc bài thử, lấy ULog từ Pixhawk và session log từ Pi về cùng
`logs/YYYY-MM-DD/` của máy quản lý dự án để phân tích. PC mô phỏng không
cần bốn ULog cũ, code Pi hoặc venv của Pi để kiểm tra model/chạy simulator.

## Chuẩn bị PC mô phỏng

Các lệnh cài dưới đây dành cho Ubuntu 22.04 sạch trong môi trường riêng,
không chạy bộ cài này trên máy workspace Ubuntu 26.04 hiện tại.

```bash
sudo apt update
sudo apt install git python3-venv gazebo libgazebo11 libgazebo-dev
git clone --branch v1.16.0 --recursive \
  https://github.com/PX4/PX4-Autopilot.git ~/PX4-Autopilot-v1.16
cd ~/PX4-Autopilot-v1.16
bash Tools/setup/ubuntu.sh --no-nuttx --no-sim-tools
DONT_RUN=1 make px4_sitl_default gazebo-classic
```

`--no-sim-tools` tránh cài thêm simulator khác; Classic đã cài riêng ở trên.
Lệnh `DONT_RUN=1` chỉ build plugin, chưa khởi chạy một phiên PX4 SITL.
Plugin `.so` phải nằm trong
`~/PX4-Autopilot-v1.16/build/px4_sitl_default/build_gazebo-classic`.
Nếu package/dependency xung đột, xem hướng dẫn Classic của PX4 trước khi
chấp nhận gỡ package. Các bước này chưa được chạy trong workspace hiện tại.

Tại thư mục gốc bản dự án trên PC mô phỏng:

```bash
python3 -m venv simulation/.venv
simulation/.venv/bin/python -m pip install -r simulation/requirements.txt
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
python3 simulation/x500/check_setup.py --px4 ~/PX4-Autopilot-v1.16
```

`--static` trả thành công khi model/tài nguyên hợp lệ dù runtime còn thiếu.
Lệnh không có `--static` đòi hỏi binary Classic 11 và đầy đủ plugin model.
Báo cáo riêng `observer_dependencies_ok` cho thư viện `pymavlink`.
Các lệnh kiểm tra này không mở cổng serial, không gửi ARM hay chạy simulator.
Plugin có file chưa bảo đảm mọi shared-library dependency đã load được;
bước `--validate` và runtime tiếp theo vẫn cần thiết.

## Chuẩn bị Pixhawk và Pi cho HITL

Tháo cánh, dùng nguồn và kết nối phù hợp, sao lưu tham số UAV thật trước
khi đổi cấu hình. Trong QGC, thiết lập HITL và chọn airframe quad X tương
ứng cấu hình PX4, xác nhận `SYS_HITL=1` sau reboot. Pi dùng profile `hitl`.
Giữ các giá trị/tham số bay thật đã sao lưu để phục hồi trước bay thật.
File hardware overlay chỉ cấu hình giao tiếp, không tự khôi phục airframe,
motor output hoặc calibration của UAV thật sau HITL.

Bốn log bay ngày 24/10 dùng PX4 release/1.17, SYS_HITL=0. Model được tạo
với nguồn PX4 v1.16; tương thích firmware bo hiện tại còn phải kiểm tra
bằng runtime. Hướng dẫn này không yêu cầu tự flash/downgrade firmware.
PX4 cũng ghi rõ HITL được cộng đồng duy trì và cần kiểm tra tương thích
phiên bản. [PX4 HITL](https://docs.px4.io/v1.16/en/simulation/hitl).

1. Pixhawk USB nối PC; TELEM2 nối Pi, baud/Onboard mode khớp README.
2. Trong QGC, xem gán actuator/HIL motor 1–4, cấu hình RC và failsafe phù
   hợp bài thử. Không vô hiệu hóa kiểm tra trên cấu hình bay thật để vượt lỗi HITL.
3. Đóng QGC/USB AutoConnect trước khi Gazebo giữ USB. Khi mở lại QGC,
   dùng UDP do simulator forward, không giành lại cổng USB.
4. Tìm thiết bị thực bằng `ls -l /dev/serial/by-id/`. Người chạy Gazebo
   cần quyền đọc/ghi cổng; nếu thêm nhóm `dialout`, đăng xuất/đăng nhập lại.

Model tạo sẵn chứa serial path máy đã tạo nó. Tạo lại cho thiết bị của bạn:

```bash
python3 simulation/x500/prepare.py \
  --px4 ~/PX4-Autopilot-v1.16 \
  --serial /dev/serial/by-id/USB_PIXHAWK_CUA_BAN --baud 921600
python3 simulation/x500/check_setup.py \
  --px4 ~/PX4-Autopilot-v1.16 --require-device
python3 simulation/x500/launch.py --px4 ~/PX4-Autopilot-v1.16 --validate
```

`--validate` kiểm tra SDF của cả model và world bằng công cụ Gazebo; không
mở serial hoặc khởi chạy mô phỏng. `prepare.py` đọc geometry/dynamics từ
PX4 source đã chọn, tạo lại model và cập nhật provenance. Xem lại kết quả
và chạy test sau mỗi lần thay nguồn.

`simulation/params/x500_hitl.params` chỉ giữ cấu hình HIL Quad-X,
SYS_HITL và giao tiếp Pi. Giá trị tuning bay cũ và các dòng ghi đè failsafe
đã được bỏ vì chưa có log mới xác thực. File không thay thế cấu hình đầy
đủ; xem và thiết lập failsafe/RC phù hợp bài thử trong QGC trước ARM.
Cần chạy lại mô phỏng để đo hover, tốc độ, đáp ứng và lưu log trước khi
xuất bộ tuning mới. Không chuyển tuning mô phỏng sang UAV thật.

## Kiểm tra liên kết khi DISARM

Khi đã tháo cánh, xác nhận DISARM và không gửi ARM trong suốt bài thử:

```bash
simulation/.venv/bin/python simulation/tests/smoke_test.py \
  --px4 ~/PX4-Autopilot-v1.16 --seconds 40 --confirm-disarmed
```

Bài thử tự mở Gazebo headless, quan sát heartbeat/actuator/ước lượng và đọc
pose model. Simulator phải còn chạy; pose phải có 6 số hữu hạn; heartbeat,
actuator, local position và landed state phải mới trong 3 s. Bất kỳ
heartbeat ARM nào trong phiên cũng làm bài thử không đạt, dù sau đó đã disarm.
Bình thường công cụ đóng Gazebo khi kết thúc. Nếu mẫu cuối vẫn ARMED,
công cụ báo PID và giữ simulator chạy để người vận hành phục hồi/disarm
trước khi ngắt HIL. Kết quả nằm trong
`simulation/artifacts/connection-*.json` cùng `.log`. Cần DISARM, ON_GROUND,
ước lượng tốc độ dưới 0,5 m/s, pose đọc được và liên kết có actuator.
Đây là smoke test trên thiết bị, không nằm trong `unittest discover`.
Kết quả luôn ghi `flight_verified=false`; chưa kiểm tra TAKEOFF hay PID.

## Chạy và kiểm chứng luồng bay

Mở phiên mô phỏng tương tác:

```bash
PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
python3 simulation/x500/launch.py --px4 ~/PX4-Autopilot-v1.16
```

Pi dùng console với `--profile hitl` theo README. Thử từng bước:
`takeoff → chờ HOLD → fly x y → chờ HOLD → land → chờ disarm/ON_GROUND`.
Thử khóa tọa độ khi TAKEOFF/FLY, timeout, ưu tiên LAND và QGC tiếp quản.
Đối chiếu cả pose mô phỏng lẫn ước lượng PX4; một cờ tới đích trên Pi
không thay thế kiểm tra chuyển động thực trong simulator.

Ở terminal khác, đọc dữ liệu bằng một observer duy nhất:

```bash
simulation/.venv/bin/python simulation/x500/observe.py --seconds 30
gz model -m x500_hitl -p
```

Observer dùng UDP 14540, QGC thường dùng 14550. System ID mặc định là 1;
truyền `--system-id` đúng với Pixhawk cho observer/smoke test khi dùng ID khác. Không chạy nhiều observer
cùng tranh một cổng. `inspect_fc.py` đọc identity/tham số qua USB chỉ khi
Gazebo và QGC đã nhả cổng. Lưu ULog Pixhawk và session log Pi cho mỗi bài.

Sau hạ cánh, xác nhận DISARM/ON_GROUND rồi dừng terminal Gazebo hoặc chạy:

```bash
bash simulation/x500/stop_gazebo.sh --disarmed
```

Script dừng các tiến trình Gazebo Classic trên máy, nên dùng môi trường
mô phỏng riêng và chỉ mở một phiên. Không dừng HIL khi Pixhawk còn ARM.

Mô hình hiện là môi trường nền phẳng để kiểm tra điều khiển, không phải
bản sao sân bay hay mô hình nhiễu/rung của UAV thật. Bài thử chỉ đạt khi
có báo cáo runtime và log của chính phiên thử; kiểm tra tĩnh không chứng
minh đã khắc phục lỗi la bàn, nguồn/Pi hoặc clipping trong bốn ULog cũ.
