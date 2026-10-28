# Chuyển từ HITL sang UAV thật: PC → Pi → Pixhawk

Sơ đồ mong muốn:

```text
QGroundControl trên PC ── UDP 14550 ──┐
                                     Pi / MAVLink Router ── USB Type-C ── Pixhawk PX4
Terminal trên PC ── SSH ── Pi/console ── UDP 127.0.0.1:14540 ──┘
```

PC dùng UDP để QGC nhận/gửi **MAVLink**, còn `arm`, `takeoff`, `fly`,
`land` được gõ trong terminal console sau khi SSH vào Pi. Console không
có API nhận các chuỗi lệnh bay từ UDP bên ngoài. Router là tiến trình duy
nhất mở USB; console dùng UDP loopback trên Pi. Không chạy console mở
`/dev/ttyACM0` đồng thời với router. [Cú pháp và hành vi endpoint của
MAVLink Router](https://github.com/mavlink-router/mavlink-router#running).

## 1. Phục hồi cấu hình PX4 của UAV thật

Tháo cánh khi chuyển cấu hình, kiểm tra motor hoặc thử ARM trên bàn. Kết
nối Pixhawk trực tiếp với QGC để sao lưu toàn bộ tham số hiện tại. Nếu
còn bản sao UAV thật trước HITL, đối chiếu/khôi phục bản đó; nếu không,
cấu hình lại từng phần trên chính UAV trong QGC. Có thể lưu/nạp tham số
tại màn hình Parameters của QGC; [PX4 hướng dẫn](https://docs.px4.io/v1.17/en/advanced_config/parameters).

[`controller/params/hardware.params`](../params/hardware.params) chỉ là
**overlay một phần**, không phải bản sao đầy đủ và chưa được xác thực bằng
chuyến bay thật. File đặt `SYS_HITL=0`, `SYS_AUTOSTART=4001` (Generic
Quad-X), xóa HIL actuator và hai breaker, đặt 6S cùng giới hạn bay chậm
dạng ứng viên. Nó không chứa ánh xạ output/motor, calibration, battery
scaling, hover/PID của UAV thật hoặc hành động khi mất Offboard. Không nạp
file này như một cấu hình bay hoàn chỉnh; kiểm tra airframe thật trước
khi dùng `SYS_AUTOSTART=4001`. File HITL ở `simulation/params/` chỉ dành
cho model X500 2,0893 kg, không chuyển các giá trị hover/PID sang UAV
thật khoảng 5–6 kg.

Trong QGC, sau khi phục hồi cấu hình thật và reboot, kiểm tra:

1. `SYS_HITL=0`; đúng loại Quad-X, kích thước, thứ tự motor, chiều quay
   và output ESC. Kiểm tra actuator từng motor **khi đã tháo cánh**.
   [Hướng dẫn actuator PX4](https://docs.px4.io/v1.17/en/config/actuators).
2. IMU, compass, GPS, radio/joystick, pin 6S và bộ đo điện áp/dòng đã
   được cấu hình/calibrate trên UAV thật. `BAT1_N_CELLS=6` không tự đặt
   đúng hệ số đo pin. Kiểm tra cảnh báo preflight của QGC.
3. Kiểm tra `COM_OF_LOSS_T`, `COM_OBL_RC_ACT`, mất datalink/RC, pin thấp,
   RTL/LAND và geofence theo sân bay thử. Các giá trị HITL không tự được
   xóa khi không có trong overlay; xem [PX4 Offboard loss](https://docs.px4.io/v1.17/en/flight_modes/offboard).
4. Xác nhận cổng USB MAVLink của Pixhawk hoạt động sau khi đổi khỏi HITL;
   `MAV_1_*` và `SER_TEL2_BAUD` trong overlay dành cho TELEM2, không cấu
   hình cổng USB. Bốn log cũ từng có lỗi compass/IMU, trượt x/y và mất
   Offboard; cần ULog mới để chứng minh các lỗi đó đã hết.

## 2. Triển khai code và nối mạng

Ví dụ Pi là `192.168.50.1`. PC và Pi phải cùng mạng. Trên PC chứa
repository hiện tại, sao chép phần controller tới release trên Pi khi
Pixhawk đã DISARM và console cũ đã đóng:

```bash
ssh pi@192.168.50.1 'mkdir -p ~/uav/releases/2026-10-26/controller'
rsync -av --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='session-logs/' controller/ \
  pi@192.168.50.1:~/uav/releases/2026-10-26/controller/
```

Trên Pi, từ thư mục release:

```bash
cd ~/uav/releases/2026-10-26/controller
python3 -m venv .venv
.venv/bin/python -m pip install -r pi/requirements.txt
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Cắm USB Type-C Pixhawk vào Pi; kiểm tra tên thiết bị (thường là
`/dev/ttyACM0`, nhưng có thể khác) và quyền truy cập serial:

```bash
ls -l /dev/serial/by-id/
ls -l /dev/ttyACM*
```

MAVLink Router phải có trên Pi (`command -v mavlink-routerd`). Nếu chưa
có, cài theo [README chính thức](https://github.com/mavlink-router/mavlink-router#installation)
cho hệ điều hành Pi. Chỉ chạy **một** instance router; dừng dịch vụ
router cũ dùng cùng USB trước khi chạy lệnh bên dưới.

## 3. Router trên Pi và QGC trên PC

Mở terminal thứ nhất trên Pi, từ thư mục release. Thay `IP_PC` bằng IPv4
thực của PC đang chạy QGC và `/dev/ttyACM0` bằng thiết bị Pixhawk thực tế:

```bash
bash tools/run_hardware_router.sh IP_PC /dev/ttyACM0
```

Script tạo cấu hình tạm, tắt TCP server mặc định của router và chỉ dùng
USB Pixhawk cùng hai endpoint UDP nêu trong sơ đồ. Giữ router chạy. Nếu
Pi đã có dịch vụ router giữ USB, dừng dịch vụ đó trước. PC mở QGC, dùng
UDP port 14550 và xác nhận nhìn thấy đúng Pixhawk, `DISARM`,
`ON_GROUND`, tham số/cảnh báo đúng UAV thật. Terminal PC kết nối Pi qua
SSH. **QGC ở sơ đồ này cũng phụ thuộc Pi/router**: nếu Pi tắt, cả console
lẫn QGC đều mất đường tới Pixhawk. Cần xác định đường điều khiển dự phòng
độc lập với Pi và hành động PX4 khi mất Offboard trước chuyến bay thật.

Trong terminal PC khác:

```bash
ssh pi@192.168.50.1
cd ~/uav/releases/2026-10-26/controller
.venv/bin/python pi/console.py --profile hardware \
  --connection udpin://127.0.0.1:14540 --check
```

`--check` chỉ đọc trạng thái rồi thoát. Cần thấy `connected=true`,
`SYS_HITL=0`, `armed=false`, `ON_GROUND`, `health_all_ok=true` và dữ liệu
telemetry còn mới. `x/y/z` local NED có thể khác 0. Nếu QGC/console
không có telemetry, kiểm tra IP PC, firewall UDP 14550, đường USB,
quyền serial và router trước khi thử ARM. Không đổi profile hoặc tắt
preflight check để đi qua lỗi kết nối.

## 4. Quy trình trước bay

### Kiểm tra trên đất, tháo cánh

1. Cấp nguồn Pi ổn định và cấp nguồn Pixhawk/power module theo sơ đồ UAV.
   Xác nhận pin 6S, điện áp/dòng trong QGC hợp lý so với phép đo độc lập.
   Trên Pi chạy `vcgencmd get_throttled`; nếu có cờ thiếu áp hoặc Pi/USB
   ngắt kết nối thì dừng kiểm tra và xử lý nguồn. Nguồn USB chỉ đủ để đọc
   Pixhawk, không chứng minh đường pin, power module và ESC đã đạt.
2. Trong QGC, kiểm tra Quad-X, vị trí đấu AUX1–4, thứ tự/chiều quay motor,
   compass, IMU, GPS, safety button và RC/joystick. Thử motor chỉ khi đã
   tháo cánh. Sau mỗi reboot, kiểm tra lại safety: bản tham số hiện tại có
   `CBRK_IO_SAFETY=0`, vì vậy PX4 có thể yêu cầu nhấn nút vật lý. Không
   bỏ qua preflight chỉ để ARM.
3. Đọc lại bản xuất tham số đầy đủ và chọn hành động an toàn phù hợp với
   sân bay thử. Bản `uav_check.params` ngày 27/10/2026 có
   `COM_OF_LOSS_T=1`, `COM_OBL_RC_ACT=0` (mất Offboard → Position),
   `NAV_DLL_ACT=0` (mất QGC không kích hoạt datalink failsafe),
   `COM_LOW_BAT_ACT=0` (pin critical chỉ cảnh báo) và hai giới hạn geofence
   bằng 0. Các giá trị này không được xác nhận là phù hợp cho chuyến bay
   thật. Nếu chỉ có QGC qua Pi thì không có đường tiếp quản khi Pi tắt;
   chuẩn bị RC hoặc telemetry độc lập và kiểm tra nó trước khi lắp cánh.
4. Chạy router ở terminal Pi thứ nhất theo mục 3. Trên PC mở QGC, chờ
   kết nối liên tục; `Comms Lost` là điều kiện dừng. Đưa UAV ra nơi GPS
   nhận tốt và mở **Fly View → Arming Check Report**: xử lý từng cảnh báo
   về safety, điều khiển thủ công, GPS/compass, vị trí, pin và cảm biến.
   `COM_ARM_WO_GPS=1` không tạo vị trí hợp lệ cho Offboard theo local NED.
5. Trên Pi chạy lệnh `--check` ở mục 3. Chỉ tiếp tục nếu
   `connected=true`, `SYS_HITL=0`, `phase=IDLE`, `armed=false`,
   `landed_state=ON_GROUND`, `health_all_ok=true`, telemetry còn mới và
   `flight_termination=false`. `x/y/z` local khác 0 không tự nó là lỗi.

Có thể thử `arm` rồi `disarm` **trên đất khi tháo cánh**, theo dõi QGC và
Pi. Bài thử này chưa xác nhận TAKEOFF/LAND. Chỉ lắp cánh sau khi đã hoàn
tất cấu hình, nguồn, cảm biến, motor, đường tiếp quản và điều kiện bay ở
địa điểm thử. [PX4 Arming Check Report](https://docs.px4.io/v1.17/en/flying/pre_flight_checks),
[PX4 actuator testing](https://docs.px4.io/v1.17/en/config/actuators).

## 5. Quy trình trong bay

Mở console ở terminal Pi thứ hai, giữ router và QGC đang hoạt động:

```bash
cd ~/uav/control
.venv/bin/python pi/console.py --profile hardware \
  --connection udpin://127.0.0.1:14540 --height 2 --enable-actuation
```

Tại `UAV>`, bài bay đầu chỉ kiểm tra TAKEOFF/HOLD/LAND:

```text
status
arm
status
takeoff
status
land
status
```

Gửi từng lệnh và quan sát UAV/QGC. `arm` có thể tự DISARM nếu không
TAKEOFF trong `COM_DISARM_PRFLT` (bản xuất hiện tại: 10 giây); xem lại
`status` nếu chờ lâu. `takeoff` chụp x/y/z tại thời điểm cất cánh và
đặt z đích cao hơn 2 m. ACK `takeoff` chỉ xác nhận ARM + OFFBOARD, chưa
xác nhận đạt 2 m. Chờ `phase=HOLD`, `takeoff_complete=true`, sai số và
độ cao trong `status` phù hợp trước khi thử lệnh khác. Bộ giám sát cần
sai số ngang ≤0,5 m, cao ≤0,3 m, yaw ≤10° trong 2 giây; quá 60 giây
sẽ yêu cầu HOLD nhưng không đánh dấu TAKEOFF hoàn tất.

Chỉ trong chuyến thử tiếp theo, khi HOLD đã xác nhận, dùng `fly X Y`.
`X/Y` là vị trí **tuyệt đối** theo local NED của PX4 (Bắc/Đông), không
phải số mét di chuyển từ điểm đang đứng. Xem x/y trong `status`, chọn
đích gần và kiểm tra lại ý nghĩa tọa độ trước khi gửi. Giữ lệnh `land`
cho hạ cánh bình thường. `disarm` gọi dừng motor cưỡng bức, có thể làm
UAV rơi nếu dùng trên không.
Lệnh `return-home` chỉ dùng sau TAKEOFF đã hoàn tất, có GPS điểm cất cánh
được Pi lưu và đích hiện tại đã Cancel/hoàn tất. Pi gửi waypoint về vị trí
đó ở độ cao đang giữ; khi PX4 hoàn
tất, UAV HOLD trên không. Muốn hạ cánh phải gõ `land` riêng. Chức năng này
chưa thử HITL/bay thật; xem [WEB_GPS_MISSION.md](WEB_GPS_MISSION.md).

Nếu UAV lệch ngoài vùng thử, mất vị trí, mất liên kết hoặc đổi mode ngoài
ý muốn, ngừng gửi đích mới và dùng đường điều khiển dự phòng đã chuẩn bị
để xử lý theo tình huống. Không giả định QGC qua Pi còn hoạt động khi Pi
tắt. Nếu console vẫn kết nối và PX4 còn phản hồi, dùng `land`; sau khi
LAND được ACK, chờ mode LAND, `ON_GROUND` và DISARM. PX4 xử lý mất luồng
Offboard theo tham số failsafe thực trên bo, không theo thông báo của Pi.
[PX4 Offboard và mất luồng](https://docs.px4.io/v1.17/en/flight_modes/offboard).

## 6. Quy trình sau bay

1. Trong `status` và QGC, xác nhận `land_mode_confirmed=true` trong lúc
   hạ, sau đó `landed_state=ON_GROUND` và `armed=false`. Nếu không có xác
   nhận mới, tiếp tục giám sát; không coi ACK LAND là đã chạm đất.
2. Nhập `exit` sau khi đã DISARM. Chỉ sau đó dừng router và ngắt nguồn
   động lực; tắt Pi theo cách bình thường. Không rút nguồn Pi khi còn
   đang bay hoặc chưa lưu log.
3. Lưu ULog PX4, log QGC nếu có và `~/uav/control/session-logs/` trên Pi.
   Ghi lại giờ bay, mã phiên log, tham số vừa thay đổi, trạng thái pin,
   điều kiện GPS/gió và bất thường (mất Wi-Fi, trượt x/y, RTL). Đối chiếu
   log mới với bốn ULog cũ trước khi mở rộng bài bay.
