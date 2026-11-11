# Chuẩn bị triển khai trên UAV thật

Đường bay thật dự kiến:

```text
Web/backend → MQTT → Pi/control → IPC → Pi/flight → MAVLink Router → USB Pixhawk/PX4
                                             QGC PC ← UDP 14550 ← Router
```

Hiện chỉ có mã và unit test bằng mock cho hai service. Chưa có bài bay thật
qua đường MQTT/IPC này. [`hardware.params`](../params/hardware.params) là
overlay **ứng viên** cho khung UAV thật, không phải cấu hình hoàn chỉnh
hay tuning đã kiểm chứng. Xem cấu trúc và các phần còn thiếu tại
[PI_SERVICES.md](PI_SERVICES.md).

## 1. Pixhawk và tham số

Trước khi chuyển từ HITL về UAV thật, sao lưu và đọc lại toàn bộ tham số
trên đúng Pixhawk/firmware. File `hardware.params` yêu cầu `SYS_HITL=0`,
nhưng nạp overlay không tự khôi phục mọi giá trị đã từng sửa ở HITL.
Trên cùng Pixhawk, phải đọc và cấu hình riêng `COM_OBL_RC_ACT`,
`COM_OF_LOSS_T`, `MPC_THR_HOVER` và `MPC_USE_HTE` trước bay thật: đây là
các giá trị có trong overlay HITL nhưng không có trong overlay thật, nên
giá trị cũ có thể còn lưu trên bo. Không sao chép `MPC_THR_HOVER=0.74`
của X500 sang UAV 5–6 kg nếu chưa đo/tuning trên chính UAV.
Đối chiếu trong QGC:

- Airframe Quad-X, AUX1–4/motor mapping, thứ tự và chiều quay motor, ESC.
- IMU, compass, GPS, MAVLink joystick, safety, pin 6S và power module.
  Overlay đặt `COM_RC_IN_MODE=1`: PX4 không nhận tay điều khiển RC truyền
  thống. Nếu joystick QGC đi qua Pi/router, mất Pi cũng làm mất đường
  điều khiển đó; xác nhận phương án tiếp quản độc lập trước bay.
- MAVLink USB/TELEM2, Offboard loss, RC loss, datalink loss, pin thấp,
  geofence và hành động khi Pi/router mất nguồn.
- `MIS_TAKEOFF_ALT=2.0` trong overlay là độ cao cất cánh mặc định của PX4;
  Pi cũng đặt TAKEOFF 2 m. Nạp overlay qua QGC, reboot và đọc lại giá trị
  trên bo. `MIS_TAKEOFF_ALT` không phải ngưỡng tối thiểu của Return Home
  có waypoint độ cao tường minh.
- `EKF2_HGT_REF=0`, `EKF2_GPS_CTRL=5`: barometer là mốc độ cao, GPS vẫn
  cung cấp vị trí ngang và vận tốc nhưng không hợp nhất độ cao GPS. Kiểm tra
  `EKF2_BARO_CTRL=1` trên bo; overlay không ghi đè tham số này. Đây là lựa
  chọn ứng viên, chưa kiểm chứng Z trên UAV thật; đối chiếu barometer, độ
  cao và innovation trong ULog trước bay.
- `FD_FAIL_P=60`, `FD_FAIL_R=60`, hai thời gian kích hoạt `0.3 s` và
  `COM_LKDOWN_TKO=3 s` phải đọc lại trên đúng Pixhawk sau khi nạp overlay.
  PX4 chỉ khóa motor khi pitch **hoặc** roll vượt 60° đủ lâu trong cửa sổ
  cất cánh; đây không phải phép đo góc nghiêng tổng hợp hay quy tắc dừng
  motor mọi lúc trên không. Sau cửa sổ này, hành vi failure detector còn
  phụ thuộc cấu hình flight termination riêng của PX4. Xem
  [tham chiếu tham số PX4 v1.17](https://docs.px4.io/v1.17/en/advanced_config/parameter_reference).
- Tham số PID/hover của UAV thật; không dùng giá trị X500 HITL cho UAV
  5–6 kg, motor 3120-700 kV và cánh “12.45” khi chưa đo trên chính UAV.

Thử motor chỉ trên bàn và đã tháo cánh. Không dùng việc unit test đạt
để suy ra motor, cánh, cảm biến hoặc failsafe đã đúng. QGC cần hiện
DISARM, ON_GROUND, preflight/arming check đạt và telemetry mới trước mọi
thử nghiệm có chuyển động.
Kiểm tra bằng HITL và quan sát QGC Messages/ULog trước khi bay thật;
không thử làm lật UAV thật khi cánh đang lắp. Cơ chế PX4 chạy trên Pixhawk,
không phụ thuộc MQTT/Pi còn kết nối.

## 2. Pi, USB và QGC

Pi nối cổng USB Type-C Pixhawk. Kiểm tra tên thật của thiết bị:

```bash
ls -l /dev/serial/by-id/
ls -l /dev/ttyACM*
command -v mavlink-routerd
```

Nếu dùng MAVLink Router, nó là tiến trình duy nhất mở USB Pixhawk;
flight service kết nối `udpin://127.0.0.1:14540` trên Pi, QGC trên PC
nhận UDP 14550. Chỉ một flight service/console dùng endpoint 14540.
Script router có sẵn ở [`run_hardware_router.sh`](../tools/run_hardware_router.sh),
cần thay IP PC và tên `/dev/ttyACM*` bằng giá trị thực tế. QGC qua router
phụ thuộc Pi; khi Pi tắt, đường QGC đó cũng mất. Cần kiểm tra một đường
tiếp quản độc lập trước bay thật.
Hai unit systemd mẫu không tự khởi động router; nếu chạy service tự động,
router phải hoạt động riêng và endpoint UDP 14540 phải có heartbeat trước
khi mong đợi `status` kết nối được.

## 3. Cài code và xác minh chỉ đọc

Đặt nội dung `controller/` hiện tại trong `~/uav-gps` trên Pi, đúng với
đường dẫn của hai unit systemd mẫu. Cài hai requirements bằng venv tại đó:

```bash
cd ~/uav-gps
# Giữ venv đã có, kể cả symlink; chỉ tạo khi đường dẫn hoàn toàn chưa tồn tại.
if [ ! -e .venv ] && [ ! -L .venv ]; then python3 -m venv .venv; fi
test -x .venv/bin/python
readlink -f .venv
.venv/bin/python -m pip install -r pi/flight/requirements.txt -r pi/control/requirements.txt
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -q
```

Với router và Pixhawk đã kết nối, chạy flight service **không có**
`--enable-actuation` để đọc status; control service có thể ở trực tuyến
và báo lỗi flight nếu tiến trình này không sẵn sàng. Mẫu systemd
[`uav-flight.service`](../systemd/uav-flight.service) cũng mặc định chỉ đọc.

```bash
.venv/bin/python pi/flight/service.py --profile hardware \
  --connection udpin://127.0.0.1:14540 \
  --socket /tmp/uav-flight.sock
.venv/bin/python pi/flight/client.py status
```

Hai lệnh trên chạy ở hai terminal. Status cần khớp `SYS_HITL=0`,
`connected=true`, `armed=false`, `ON_GROUND`, health và vị trí mới.
Nếu không đúng, sửa nguyên nhân trên phần cứng/tham số/kết nối; không
đổi profile chỉ để qua kiểm tra.

## 4. Điều kiện trước khi cho web quyền bay

Đường hai service phải qua thử HITL A→B, pause/resume, cancel, return-home,
return-height, LAND và xác nhận disarmed bằng telemetry/ULog trước. Sau đó
topic `control` hiện chỉ có payload sáu trường, không có ID/hạn dùng từ
backend và chưa đủ chống phát lại qua reboot. Cần chạy thử
trên bàn với UAV thật đã tháo cánh, kiểm tra timeout, mất mạng/Pi/router,
nguồn và đường tiếp quản độc lập.

Chỉ sau các bước đó mới xem xét bật `--enable-actuation` cho profile
`hardware` trong cấu hình vận hành riêng. Control Service không phát ACK MQTT;
phản hồi IPC cũng không chứng minh UAV đã tới B hoặc đã hạ cánh. Luôn đối
chiếu phase/mode/armed/landed trong status, QGC và ULog PX4. Log Pi
ở thư mục `--log-dir`; QGC Messages và ULog là các nguồn độc lập.
