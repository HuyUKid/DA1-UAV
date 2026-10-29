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
Đối chiếu trong QGC:

- Airframe Quad-X, AUX1–4/motor mapping, thứ tự và chiều quay motor, ESC.
- IMU, compass, GPS, RC/joystick, safety, pin 6S và power module.
- MAVLink USB/TELEM2, Offboard loss, RC loss, datalink loss, pin thấp,
  geofence và hành động khi Pi/router mất nguồn.
- Tham số PID/hover của UAV thật; không dùng giá trị X500 HITL cho UAV
  5–6 kg, motor 3120-700 kV và cánh “12.45” khi chưa đo trên chính UAV.

Thử motor chỉ trên bàn và đã tháo cánh. Không dùng việc unit test đạt
để suy ra motor, cánh, cảm biến hoặc failsafe đã đúng. QGC cần hiện
DISARM, ON_GROUND, preflight/arming check đạt và telemetry mới trước mọi
thử nghiệm có chuyển động.

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

## 3. Cài code và xác minh chỉ đọc

Đặt `controller/` hiện tại trong `~/uav/current/controller` trên Pi;
trên Pi cài riêng venv và hai requirements:

```bash
cd ~/uav/current/controller
python3 -m venv .venv
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
backend phải triển khai lệnh v2 có ID/hạn dùng và quyền MQTT thích hợp;
payload sáu trường legacy không đủ chống phát lại qua reboot. Cần chạy thử
trên bàn với UAV thật đã tháo cánh, kiểm tra timeout, mất mạng/Pi/router,
nguồn và đường tiếp quản độc lập.

Chỉ sau các bước đó mới xem xét bật `--enable-actuation` cho profile
`hardware` trong cấu hình vận hành riêng. Một ACK MQTT là xác nhận xử lý
yêu cầu, không phải bằng chứng UAV đã tới B hoặc đã hạ cánh. Luôn đối
chiếu phase/mode/armed/landed trong status, QGC và ULog PX4. Log Pi
ở thư mục `--log-dir`; QGC Messages và ULog là các nguồn độc lập.

OTA cập nhật phần mềm Pi và flash firmware Pixhawk **chưa triển khai**.
Không gửi URL/script/firmware qua MQTT để thực thi trên UAV thật.
