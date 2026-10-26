# Mô phỏng X500 với Gazebo Classic HITL

## Kết quả kiểm tra hiện tại

Lần kiểm tra ngày 24/10/2026 trên máy workspace trước (Ubuntu 26.04)
chỉ kiểm tra tĩnh. Ngày 26/10/2026, máy hiện tại là Ubuntu 22.04.5,
có Gazebo Classic 11.10.2 và PX4 v1.16.0/plugin đã build trong
`~/PX4-Autopilot-v1.16`. Việc có binary/plugin không thay thế kiểm tra
runtime với Pixhawk. Lần kiểm tra tiếp theo ngày 26/10 đã đạt liên kết
USB/HIL DISARM trong 40 giây trên Pixhawk FMUv6C/PX4 1.17.0: heartbeat,
actuator và local position mới, ON_GROUND, tốc độ ước lượng khoảng
0,0054 m/s, pose model hữu hạn/ổn định. Sau đó đã bay HITL trên cùng Pixhawk, xác nhận thuật toán và đo đáp ứng; xem [báo cáo bài bay](ALGORITHM_VALIDATION_2026-10-26.md).
Đã kiểm tra gói plugin dùng sẵn trên bản `simulation/` chép riêng: dependency,
load cả 12 thư viện và xác thực SDF đạt. Xem
[báo cáo bộ binary](../prebuilt/ubuntu-22.04-x86_64/VALIDATION.md).

| Hạng mục | Kết quả |
|---|---|
| XML model/world và tài nguyên mesh/texture | Kiểm tra đạt |
| Khối lượng, quán tính và hình học X500 | Giữ theo model nguồn đã lưu; tổng khối lượng link khoảng 2,0893 kg |
| Bốn motor, thứ tự, vị trí, chiều quay và hằng số | Kiểm tra tĩnh đạt; runtime X500 đã bay, lực đẩy model chưa được đối chiếu UAV thật |
| Sensor/bridge | Có IMU, GPS, magnetometer, barometer và MAVLink HIL plugin Classic |
| World | Nền phẳng 100×100 m, ánh sáng local, gravity −9,8066 m/s², bước 0,004 s / 250 Hz |
| Phụ thuộc tải model qua mạng | Nền và ánh sáng đã được đưa trực tiếp vào world |
| Môi trường trên máy hiện tại, 26/10 | Ubuntu 22.04.5, Classic 11.10.2; kiểm tra binary/plugin và xác thực SDF model/world đạt |
| USB ↔ HIL và estimator đứng yên | Smoke test DISARM 40 giây đạt trên PX4 1.17.0 |
| TAKEOFF/HOLD/FLY/LAND | Đạt trên HITL 26/10; có log, pose và báo cáo định lượng |

Các test tại `simulation/tests/test_*.py` kiểm tra model, công cụ,
tiêu chí chấp nhận quan sát và launcher trên máy khác. Test đối chiếu
body/inertial với bản X500 nguồn được lưu trong `generated/models/x500_base`.
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

## Chuẩn bị PC mô phỏng — dùng plugin đã build

Luồng mặc định dành cho **Ubuntu 22.04 x86_64**. Git đã chứa model,
mesh/texture, world và 12 thư viện `.so` cần cho X500 tại
`simulation/prebuilt/ubuntu-22.04-x86_64/lib/` (khoảng 3,3 MB).
Không cần tải source PX4 hoặc build trên PC khi dùng bộ này.
Firmware PX4 vẫn phải có trên Pixhawk thật.

Tại gốc dự án, chạy:

```bash
bash simulation/install_classic.sh
```

Script dùng `sudo apt-get` để cài Gazebo Classic 11/runtime và Python venv,
rồi cài `pymavlink` cùng dependency bằng Python wheel. Nó kiểm tra target,
checksum, dependency của plugin và SDF; không chạy compiler, không clone
PX4, không khởi chạy mô phỏng, không mở USB hoặc ghi firmware/tham số bo.
Nếu máy đã có Gazebo Classic 11 và `python3-venv`, dùng:

```bash
bash simulation/install_classic.sh --skip-system
```

Gazebo/QGroundControl là ứng dụng cài riêng; QGroundControl không được
script này tải. Venv được tạo trên từng máy và được Git bỏ qua. Lần cài
runtime/Python đầu cần Internet; bộ plugin không biến cài đặt thành offline.
Không chép thư viện Python đã cài trong Home hoặc venv lên Git.

Nguồn bộ binary là build PX4 v1.16.0/Classic hiện có trên máy dự án;
revision, trạng thái checkout, checksum và giới hạn provenance nằm trong
[manifest](../prebuilt/ubuntu-22.04-x86_64/manifest.json).
Copyright/license nằm cạnh binary; xem
[chi tiết bộ plugin](../prebuilt/ubuntu-22.04-x86_64/README.md).
Bản sao đã đổi RUNPATH sang `$ORIGIN` và bỏ debug/symbol không cần thiết;
file build gốc được giữ nguyên. Checksum dùng phát hiện sai/hỏng file, không
phải chữ ký xác thực nhà phát hành.

Kiểm tra thủ công, không mở serial hoặc chạy simulator:

```bash
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
simulation/.venv/bin/python simulation/x500/prebuilt.py
simulation/.venv/bin/python simulation/x500/check_setup.py
simulation/.venv/bin/python simulation/x500/launch.py --serial /dev/null --validate
```

Launcher/checker mặc định chọn bộ `prebuilt` nếu có. `--px4 PATH` chọn
plugin từ build source của bạn; `--plugins PATH` chọn thư mục `.so` cụ thể.
Bộ binary sẽ từ chối host khác Ubuntu 22.04 x86_64. Nếu không có thư mục
prebuilt, công cụ mới tìm cây PX4 trong `simulation/.external/` hoặc Home.
`--static` chỉ yêu cầu kiểm tra model đạt; `runtime_ok` không phải bằng chứng
HIL/estimator hay chuyển động model đã hoạt động. `--validate` kiểm tra SDF,
không khởi tạo sensor/physics hoặc kiểm thử giao tiếp Pixhawk.

### Tùy chọn cho người bảo trì: build từ source

Chỉ dùng nếu muốn tự build/thay bộ plugin. Trên Ubuntu 22.04:

```bash
bash simulation/setup_classic.sh
```

Script này tải PX4 v1.16.0 revision
`6ea3539157ca358c70a515878b77077af7d4611d` cùng Classic revision
`70683dc759cbd3ebccfa78429b564f8b1fb5d149` vào `simulation/.external/`,
cài dependency build rồi chạy
`DONT_RUN=1 make px4_sitl_default gazebo-classic`. Đây là bước biên dịch,
không phải bước bắt buộc cho người dùng bộ binary. Lệnh build không flash
Pixhawk hay chạy một phiên SITL. `setup_classic.sh --px4 PATH
--skip-system --skip-build` cho phép kiểm tra lại build đang có.

Khi chạy bản tự build, truyền rõ `--px4 PATH` cho launcher/checker/smoke test
để không chọn bộ binary mặc định. `prepare.py` vẫn cần PX4 source nếu muốn
thay geometry/dynamics; không cần tái tạo model chỉ để đổi USB/baud.
Người bảo trì có thể dùng `simulation/tools/package_classic.py --px4 PATH`
để đóng gói lại sau khi review build mới; script từ chối ghi đè bộ đã có.

Chưa kiểm thử cài apt/build từ đầu trên máy Ubuntu sạch trong lần cập nhật
này. Không suy ra tương thích mọi bản Gazebo 11 hoặc firmware từ việc load
được thư viện trên máy đóng gói. Cần thử HIL với firmware/bo thực tế.

## Chuẩn bị Pixhawk và Pi cho HITL

Tháo cánh, dùng nguồn và kết nối phù hợp, sao lưu tham số UAV thật trước
khi đổi cấu hình. Trong QGC, thiết lập HITL và chọn airframe quad X tương
ứng cấu hình PX4, xác nhận `SYS_HITL=1` sau reboot. Pi dùng profile `hitl`.
Giữ các giá trị/tham số bay thật đã sao lưu để phục hồi trước bay thật.
File hardware overlay có airframe generic Quad-X và giới hạn chuyển động
chậm dạng ứng viên, nhưng không khôi phục motor output, calibration hoặc
failsafe đã xác thực của UAV thật sau HITL.

Bốn log bay ngày 24/10 dùng PX4 release/1.17, SYS_HITL=0. Model được tạo
với nguồn PX4 v1.16; bài bay HITL 26/10 trên firmware bo 1.17.0 đã đạt
trong phạm vi [báo cáo](ALGORITHM_VALIDATION_2026-10-26.md). Hướng dẫn này không yêu cầu tự flash/downgrade firmware.
PX4 cũng ghi rõ HITL được cộng đồng duy trì và cần kiểm tra tương thích
phiên bản. [PX4 HITL](https://docs.px4.io/v1.16/en/simulation/hitl).

1. Pixhawk USB nối PC; TELEM2 nối Pi nếu dùng Pi, hoặc dùng console PC qua UDP
   loopback. Baud/Onboard mode khớp README.
2. Trong QGC, sao lưu tham số, nạp `simulation/params/x500_hitl.params`
   sau khi reset PX4 về defaults nếu thực hiện reset, reboot, đọc lại
   `SYS_HITL=1` và các giới hạn. Xem gán HIL motor 1–4, RC và failsafe phù
   hợp bài thử. Không vô hiệu hóa kiểm tra trên cấu hình bay thật để vượt lỗi HITL.
3. Đóng QGC/USB AutoConnect trước khi Gazebo giữ USB. Khi mở lại QGC,
   dùng UDP do simulator forward, không giành lại cổng USB.
4. Tìm thiết bị thực bằng `ls -l /dev/serial/by-id/`. Người chạy Gazebo
   cần quyền đọc/ghi cổng; nếu thêm nhóm `dialout`, đăng xuất/đăng nhập lại.

Model nguồn giữ serial path lịch sử. Launcher chọn cổng thực trên bản
model tạm; không cần tái sinh model chỉ để đổi USB/baud:

```bash
simulation/.venv/bin/python simulation/x500/launch.py \
  --serial /dev/null --validate
ls -l /dev/serial/by-id/
```

`--validate` kiểm tra SDF của cả model và world bằng công cụ Gazebo; không
mở serial hoặc khởi chạy mô phỏng. `/dev/null` chỉ là giá trị trong bản
model tạm ở bước này. Khi chạy HITL, dùng `--serial auto` nếu đúng một
thiết bị by-id, hoặc `--serial /dev/serial/by-id/USB_PIXHAWK_CUA_BAN`.
`--baud` mặc định 921600. Launcher kiểm tra tồn tại/quyền cổng trước khi chạy.
`check_setup.py --require-device` kiểm tra cổng ghi trong model nguồn,
không tự chọn cổng thay launcher.

Chỉ tạo lại model khi đổi source/cấu trúc. `prepare.py` đọc geometry/dynamics từ
PX4 source đã chọn, tạo lại model và cập nhật provenance. Xem lại kết quả
và chạy test sau mỗi lần thay nguồn.

`simulation/params/x500_hitl.params` chứa cấu hình HIL Quad-X, giao tiếp
TELEM2 và giới hạn bay chậm đã thử trên Pixhawk/PX4 1.17.0 ngày 26/10.
Đặt `COM_RC_IN_MODE=4` cho bài kiểm tra PC qua terminal không có radio;
console PC gửi heartbeat loại ground station. File cũng có hai breaker nguồn/
safety phục vụ HITL và hover 0,74 chỉ đúng cho model X500. Reboot sau import,
đối chiếu các tham số và preflight trong QGC trước ARM. Xem
[báo cáo bay](ALGORITHM_VALIDATION_2026-10-26.md) và file
`controller/params/hardware.params` ở gốc repo cho ứng viên bay thật.
Không chuyển hover/PID và breaker HITL sang UAV thật.

## Kiểm tra liên kết khi DISARM

Khi đã tháo cánh, xác nhận DISARM và không gửi ARM trong suốt bài thử:

```bash
simulation/.venv/bin/python simulation/tests/smoke_test.py \
  --serial auto --seconds 40 --confirm-disarmed
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
Riêng smoke test này luôn ghi `flight_verified=false` vì chỉ quan sát DISARM;
bài bay và đo đáp ứng nằm trong [báo cáo riêng](ALGORITHM_VALIDATION_2026-10-26.md).

## Console trên PC, không dùng Pi

Nếu có bản clone đầy đủ dự án, sau khi mở Gazebo, từ gốc dự án chạy:

```bash
simulation/.venv/bin/python -m pip install --only-binary=:all: -r controller/pi/requirements.txt
simulation/.venv/bin/python controller/pi/console.py --profile hitl \
  --connection udpin://127.0.0.1:14540 --check
```

Kiểm tra đọc trạng thái qua UDP trên PC ngày 26/10 đạt. Sau đó đã bay thử
với `--enable-actuation`; xem [kết quả HITL](ALGORITHM_VALIDATION_2026-10-26.md).
Lệnh `--check` bên trên vẫn chỉ đọc, không gửi ARM.
Không chạy `observe.py` hay smoke test đồng thời với console trên UDP 14540.
Gazebo giữ USB; console không mở USB lần thứ hai.

Khi trạng thái đạt yêu cầu, mở console tương tác:

```bash
simulation/.venv/bin/python controller/pi/console.py --profile hitl \
  --connection udpin://127.0.0.1:14540 --height 2 --enable-actuation
```

Console vẫn dùng cùng FSM và local NED; hardware profile chỉ chấp nhận
serial. Cách này không cần Pi, nhưng cần Pixhawk thật ở HITL. Nếu chỉ chép
riêng `simulation/`, tiếp tục dùng console trên Pi như luồng ban đầu.

## Chạy và kiểm chứng luồng bay

Mở phiên mô phỏng tương tác:

```bash
PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
simulation/.venv/bin/python simulation/x500/launch.py --serial auto
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
