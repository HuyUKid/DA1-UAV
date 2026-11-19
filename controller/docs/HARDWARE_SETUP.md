# Raspberry Pi và Pixhawk trên UAV thật

## Kết nối

```text
Pixhawk USB → một MAVLink Router trên Pi
                  ├─ 127.0.0.1:14540 → Flight Service
                  ├─ 127.0.0.1:14541 → telemetry reader
                  └─ LAPTOP_IP:14550 → QGroundControl
```

Chỉ router giữ USB. QGC chạy trên laptop; các lệnh service chạy trên Pi
qua SSH. Xác định USB và quyền truy cập:

```bash
ls -l /dev/serial/by-id/
id -nG
command -v mavlink-routerd
```

User cần quyền `dialout`. Từ terminal SSH trên Pi, mở router:

```bash
cd ~/uav-gps
UAV_LAPTOP_IP="${SSH_CONNECTION%% *}"
bash tools/run_hardware_router.sh "$UAV_LAPTOP_IP" \
  /dev/serial/by-id/usb-Auterion_PX4_FMU_v6C.x_0-if00
```

Thay tên USB bằng thiết bị thực tế. `SSH_CONNECTION` chỉ có trong phiên
SSH; IP đầu tiên là laptop. Script có đối số thứ ba nếu cần gửi QGC tới
laptop khác. Không chạy router thứ hai. Nếu mất heartbeat, kiểm tra
router, USB, log kernel và thời điểm Pi reboot để xác định đường bị ngắt.

## Chuẩn bị code và tham số

Từ PC ở gốc repository, khi UAV đã disarm, đồng bộ code:

```bash
ssh pi@192.168.50.1 'mkdir -p ~/uav-gps'
rsync -av --exclude='.venv/' --exclude='__pycache__/' --exclude='session-logs/' \
  controller/ pi@192.168.50.1:~/uav-gps/
```

Cài dependency và test theo mục bên dưới. Dùng profile
`hardware`, đọc `SYS_HITL=0`; không chạy simulator cho UAV thật.

[`hardware.params`](../params/hardware.params) là overlay một phần, không
phải cấu hình hoàn chỉnh. Nạp/đọc lại qua QGC trên đúng firmware. Cần xác
nhận airframe, motor mapping AUX/MAIN theo dây thực tế, thứ tự/chiều quay,
calibration cảm biến, power module, pin 6S, safety và failsafe. Overlay
không cung cấp calibration hoặc tuning hover/PID của UAV.

| Nhóm | Giá trị trong file |
|---|---|
| Native Takeoff | MIS_TAKEOFF_ALT=2.0 |
| Tốc độ ngang | MPC_XY_VEL_MAX=1.0, MPC_XY_CRUISE=1.0 |
| Tốc độ đứng | Max/auto lên và xuống 0.5 m/s; takeoff 0.4; LAND 0.3 |
| Mốc độ cao EKF | EKF2_HGT_REF=0, EKF2_GPS_CTRL=5; xác nhận barometer được bật trên bo |
| Nguồn điều khiển manual | COM_RC_IN_MODE=1: MAVLink joystick |
| Pin | Low 30%, critical 7%, emergency 5%, COM_LOW_BAT_ACT=2 |

Giới hạn đang đặt là ứng viên cần kiểm chứng trên UAV thật. Mô phỏng
và UAV thật đồng bộ mục tiêu chuyển động, nhưng giữ riêng airframe,
HIL, hover/PID, safety và calibration. Khi chuyển khỏi HITL, đọc lại
Offboard-loss, datalink/manual loss, geofence và các giá trị từng sửa
trên bo: bỏ một dòng khỏi overlay không phục hồi giá trị cũ. Thử motor
trên bàn phải tháo cánh. QGC qua Pi cũng mất khi Pi tắt; cần đường tiếp
quản phù hợp với cấu hình điều khiển thực tế.

## Chạy các tiến trình

Router đã chạy; terminal Pi khác mở Flight ở chế độ chỉ đọc trước:

```bash
cd ~/uav-gps
.venv/bin/python pi/flight/service.py --profile hardware \
  --connection udpin://127.0.0.1:14540 \
  --height 2 --gps-max-height 7 --gps-max-speed 1 \
  --socket /tmp/uav-flight.sock
```

Mở client ở terminal khác và kiểm tra `status`: connected, SYS_HITL=0,
DISARM/ON_GROUND, health và telemetry mới. Chỉ thêm `--enable-actuation`
khi chuyển sang phiên vận hành có quyền bay sau khi kiểm chứng mô phỏng.

Control Service nhận lệnh web; nó hỏi mật khẩu:

```bash
cd ~/uav-gps
.venv/bin/python pi/control/service.py --device-id uav01 \
  --username MQTT_USER --flight-socket /tmp/uav-flight.sock
```

Client kỹ thuật dùng cùng Flight Service:

```bash
cd ~/uav-gps
.venv/bin/python pi/flight/client.py --socket /tmp/uav-flight.sock
```

Reader telemetry trên Pi dùng endpoint 14541 để gửi trạng thái lên web.
Nó là thành phần tích hợp riêng; không thay thế Flight/Control và không
mở thêm router hoặc chiếm 14540. Hợp đồng độ cao ở
[LOGGING.md](LOGGING.md).

## Đổi tốc độ hoặc độ cao

Để chọn tốc độ nhiệm vụ S: đặt `MPC_XY_VEL_MAX` trên QGC ít nhất S,
`MPC_XY_CRUISE` theo tốc độ hành trình mong muốn; khởi động Flight với
`--gps-max-speed` ít nhất S và chọn S trên web/terminal.
Pi từ chối tốc độ vượt min của giới hạn Pi/PX4, không tự giảm payload.
Đọc lại tham số sau khi nạp, khởi động lại Flight để đọc giới hạn mới.
Tăng trần không tự tăng tốc độ của nhiệm vụ đang chọn thấp hơn.

Độ cao TAKEOFF là `--height` (2 m); `--gps-max-height` là trần nhiệm vụ,
không phải độ cao bay thực tế. Web/terminal chọn độ cao nhiệm vụ từ
TAKEOFF height tới trần này. Độ cao đứng theo launch, không theo địa hình.
Tốc độ ngang không tự thay tốc độ lên/xuống. Miền cấu hình tốc độ Pi là
0.1–10 m/s; vận hành hiện chọn trần 1 m/s.

## Sau bay

Gửi LAND, chờ ON_GROUND và armed=false trước khi dừng service/router.
Giữ log Pi và ULog trên Pixhawk để đối chiếu.

- [LOGGING.md](LOGGING.md): status, LAST_ERROR và xuất log.
- [HARDWARE_SETUP.md](HARDWARE_SETUP.md): cảnh báo 30%/15%, LAND 7%.
- [GPS_MISSION_FLOW.md](GPS_MISSION_FLOW.md): trình tự thực thi GPS.

## Cài dependency và systemd trên Pi

### Chạy trên Pi

Nội dung `controller/` được triển khai tại `~/uav-gps`. Cài dependency:

```bash
cd ~/uav-gps
if [ ! -e .venv ] && [ ! -L .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r pi/flight/requirements.txt -r pi/control/requirements.txt
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -q
```

Giữ venv hiện có, kể cả symlink hợp lệ. Với bản chỉ có controller, bài
đối chiếu tham số HITL được skip nếu không có file mô phỏng.
Nếu native MAVSDK ARM64 không nạp được, xem
[Native MAVSDK trên Pi](../../docs/FLIGHT_STATES.md#native-mavsdk-trên-pi).

Chọn đường kết nối theo [HARDWARE_SETUP](HARDWARE_SETUP.md) hoặc
[SETUP mô phỏng](../../simulation/docs/SETUP.md); mở Flight trước, Control sau, rồi
client. Các tiến trình dùng cùng socket `/tmp/uav-flight.sock`. Với USB,
router phải chạy trước Flight. Không mở thêm console trực tiếp cùng cổng.

### Systemd

Các unit trong `controller/systemd/` dùng `/home/pi/uav-gps`.
Tạo `/etc/uav/uav.env` với cấu hình thực tế:

```ini
UAV_PROFILE=hardware
UAV_CONNECTION=udpin://127.0.0.1:14540
UAV_HEIGHT=2.0
UAV_GPS_MAX_HEIGHT=7.0
UAV_GPS_MAX_SPEED=1.0
UAV_DEVICE_ID=uav01
UAV_MQTT_USERNAME=MQTT_USER
UAV_MQTT_HOST=mqtt.lacais.com
UAV_MQTT_PORT=8883
```

Đặt mật khẩu riêng trong `/etc/uav/mqtt-password`, cho user `pi` quyền
đọc. Không commit thông tin xác thực. Cài unit sau khi các lệnh thủ công
đã chạy đúng; unit Flight mặc định chỉ đọc. Quyền actuation phải được
cấu hình ở unit triển khai sau khi kiểm chứng. Router được vận hành riêng,
không do hai unit này khởi động.

Systemd dùng socket `/run/uav/flight.sock` và log `/var/lib/uav/logs`.
Client cần chọn đúng socket:

```bash
cd ~/uav-gps
.venv/bin/python pi/flight/client.py --socket /run/uav/flight.sock
```

Thư mục log client vẫn là `session-logs/services` tương đối với thư mục
làm việc; log service nằm ở `--log-dir`. Xem LOGGING khi xuất tổng hợp.

## Giám sát pin và chính sách hạ cánh

### Cấu hình đã chọn

Cả overlay thật và HITL đều chứa:

| Tham số | Giá trị | Hành vi yêu cầu |
|---|---:|---|
| BAT_LOW_THR | 0.30 | PX4 cảnh báo pin thấp ở 30% |
| BAT_CRIT_THR | 0.07 | Mức critical ở 7% |
| BAT_EMERGEN_THR | 0.05 | Mức emergency ở 5% |
| COM_LOW_BAT_ACT | 2 | PX4 LAND khi pin đạt mức critical |

Pi thêm cảnh báo `RESERVE_LOW` ở 15% trên terminal/status/log; đây là
cảnh báo của Pi, không phải ngưỡng pin thấp thứ hai trên PX4. Mức
critical/emergency được ưu tiên khi pin giảm thấp hơn.

Pi đọc ngưỡng từ bo đang kết nối và không tự gửi LAND hoặc DISARM theo
phần trăm pin. PX4 thực hiện hành động pin đã cấu hình, kể cả khi
Pi/MQTT mất kết nối. Xem
[tham chiếu tham số PX4 v1.17](https://docs.px4.io/v1.17/en/advanced_config/parameter_reference#COM_LOW_BAT_ACT).

### Status và log

Telemetry pin gồm phần trăm còn lại, điện áp, dòng điện, nhiệt độ, ID
và tuổi mẫu. Dữ liệu cũ/không có hoặc ngưỡng chưa đọc được sẽ cho UNKNOWN,
không tự coi pin là khỏe. Thay đổi trạng thái pin được ghi bằng
`BATTERY_STATE`. `status --json` chứa `battery_failsafe` là các giá trị
đã đọc từ PX4; thao tác đọc không đổi tham số trên bo.

Sửa file overlay không thay Pixhawk. Nạp đúng file, Refresh/đọc lại bốn
giá trị và khởi động lại Flight Service để đọc cấu hình mới. Trong phiên
rà soát này chưa đọc lại bo trực tiếp và chưa thử battery LAND bằng HITL.

### Kiểm chứng

Thử chính sách bằng HITL trước khi áp dụng cho UAV thật. Kiểm tra cảnh
báo và LAND khi model đang ARM/bay, giữ ULog và log Pi. LAND hạ ở vị trí
hiện tại, không chọn bãi đáp trống. Thời gian chờ failsafe và các failsafe
khác đang hoạt động ảnh hưởng thời điểm thực hiện: 7% kích hoạt hành
động cấu hình, không có nghĩa chạm đất ngay hoặc force-stop motor.

7% còn ít năng lượng dự phòng. Cần kiểm tra power module đo điện áp/dòng,
loại pin 6S/dung lượng, ngưỡng điện áp cell, sụt áp dưới tải và ước lượng
phần trăm bằng đo thực tế. Ước lượng sai có thể làm LAND sớm hoặc sụp
nguồn trước 7%. Mô phỏng cùng chính sách không xác nhận mô hình pin của
UAV thật đã đúng.
