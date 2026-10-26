# Điều khiển X500 HITL từ máy khác qua Raspberry Pi

## Sơ đồ đang được hỗ trợ

```text
Máy điều khiển ── SSH (lệnh gõ trong terminal) ──> Pi/console.py
                                                   │ UART TX/RX/GND, 921600
                                                   └──> Pixhawk TELEM2, SYS_HITL=1
Máy mô phỏng ── USB ──> Pixhawk; máy mô phỏng chạy Gazebo Classic X500
```

Lệnh `takeoff`, `fly x y`, `land` được nhập trong terminal Pi qua SSH. SSH là
đường nhận lệnh; console Pi gửi MAVLink qua UART. Bản controller hiện không có
UDP API để PC gửi trực tiếp các lệnh đó đến Pi. Nếu cần QGroundControl trên
máy mô phỏng, Gazebo chuyển MAVLink tới UDP loopback 14550 trên chính máy đó.
Không mở console PC trên UDP 14540 cùng lúc với console Pi: chỉ một chương
trình được ra lệnh bay. Không chạy thêm MAVLink router trên UART TELEM2 cùng
lúc với console Pi; chúng sẽ tranh cùng một cổng.

Bộ tham số X500 HITL nằm trên Pixhawk, không nạp từ Pi khi chạy console.
Gói kèm `simulation/params/x500_hitl.params` để test đối chiếu hai profile
chạy được sau khi giải nén; file này không được tự nạp vào Pixhawk từ Pi. Không dùng `controller/params/hardware.params` trong HITL.

## Chuyển và cài code

Từ máy mô phỏng, chép `dist/uav-pi-hitl-20261026.tar.gz` sang máy điều khiển
bằng phương tiện bạn chọn. Trên máy điều khiển, thay `<PI_IP>` bằng địa chỉ
Pi thấy được từ máy đó:

```bash
scp uav-pi-hitl-20261026.tar.gz pi@<PI_IP>:~/
ssh -t pi@<PI_IP>
```

Trên Pi, tạo bản phát hành riêng để không ghi đè code cũ:

```bash
mkdir -p ~/uav/releases/2026-10-26
tar -xzf ~/uav-pi-hitl-20261026.tar.gz -C ~/uav/releases/2026-10-26
cd ~/uav/releases/2026-10-26/controller
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r pi/requirements.txt
.venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -q
```

Nếu `python3 -m venv` thiếu, cài `python3-venv` bằng apt trên Pi rồi chạy lại.
MAVSDK được ghim `4.0.6`. Chỉ khi wheel ARM64 có lỗi native C++ runtime,
xem `docs/FLIGHT_STATES.md#native-mavsdk-trên-pi` ở repository nguồn hoặc
`tools/build_mavsdk_pi.sh` trong gói; không build nếu import/chạy đã đạt.

## Kiểm tra UART TELEM2 trên Pi

Trên Pi, kiểm tra cổng và quyền. Raspberry Pi 5 (kernel `rpi-2712`) thường
cho `/dev/serial0` trỏ tới UART10 ở **đầu debug 3 chân**, không phải
GPIO14/15 ở header 40 chân. Nếu dây TELEM2 nối GPIO14/15 (pin vật lý
8/10), cần UART0 (`/dev/ttyAMA0`) được bật và không bị serial console giữ.
Chỉ chọn thiết bị sau khi đối chiếu dây thực tế:

```bash
ls -l /dev/serial0 /dev/ttyAMA0 /dev/ttyAMA10 2>/dev/null
readlink -f /dev/serial0
grep -E "^(dtparam=uart0|enable_uart=)" /boot/firmware/config.txt || true
cat /proc/cmdline
pinctrl get 14 15
id -nG
```

Trên Raspberry Pi OS thường cần bật serial hardware và tắt serial login
console trong `sudo raspi-config`, rồi reboot Pi. Với Pi 5 và dây ở GPIO14/15,
chỉ dùng `/dev/ttyAMA0` sau khi xác nhận UART0 xuất hiện và đúng pin.
Không bật `uart0_console` cho cổng điều khiển MAVLink vì nó cấp login shell.
Nếu GPIO14/15 chưa có chức năng UART0, xem `dtoverlay -h uart0-pi5`, thêm
`dtoverlay=uart0-pi5` vào `/boot/firmware/config.txt` rồi reboot và kiểm tra
lại `pinctrl get 14 15`. Xem tài liệu UART chính thức của Raspberry Pi
trước khi đổi config. Nếu thiếu quyền cổng, thêm user `pi` vào nhóm `dialout`,
đăng xuất và đăng nhập lại. TELEM2 dùng TX↔RX, RX↔TX, GND, logic level phù
hợp; tham số PX4 hiện dự kiến `MAV_1_CONFIG=102`, `MAV_1_MODE=2`,
`MAV_1_FLOW_CTRL=0`, `SER_TEL2_BAUD=921600`.

## Bắt đầu HITL

1. Trên máy mô phỏng: Pixhawk đã nạp bộ HITL, tháo cánh; đóng QGC nếu đang
   giữ USB. Chạy Gazebo trước:

   ```bash
   cd /home/lacais/Projects/UAV
   PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
   simulation/.venv/bin/python simulation/x500/launch.py --serial auto
   ```

2. Với `COM_RC_IN_MODE=4` và console Pi là MAVSDK companion, mở
   QGroundControl **sau** Gazebo trên máy mô phỏng qua UDP 14550 để cung
   cấp kết nối ground station/giám sát. QGC không được chiếm USB mà Gazebo
   giữ. Pi console qua TELEM2 chưa được thử bay end to end trên phần cứng
   hiện tại.

3. Từ máy điều khiển, SSH vào Pi; tại thư mục `~/uav/releases/2026-10-26/controller`, kiểm tra chỉ đọc. Ví dụ dưới đây dùng `/dev/ttyAMA0` **chỉ khi dây ở GPIO14/15 và UART0 đã được xác minh**; nếu dây ở đầu debug 3 chân, dùng thiết bị đã xác minh của đầu đó:

   ```bash
   .venv/bin/python pi/console.py --profile hitl \
     --connection serial:///dev/ttyAMA0:921600 --check
   ```

   Cần thấy `SYS_HITL=1`, `connected=true`, `armed=false`, `ON_GROUND`,
   `health_all_ok=true`, telemetry mới và không có `flight_termination`.
   Nếu thiếu heartbeat, kiểm tra UART/baud/wiring/truyền MAVLink TELEM2;
   không ARM để dò lỗi.

4. Khi các điều kiện trên đạt và model Gazebo đứng yên hợp lý, mở phiên
   điều khiển trên Pi:

   ```bash
   .venv/bin/python pi/console.py --profile hitl \
     --connection serial:///dev/ttyAMA0:921600 --height 2 --enable-actuation
   ```

   Tại `UAV>`: `status`, `takeoff`; chờ `phase=HOLD`,
   `takeoff_complete=true`, `can_send_target=true`. Xem `launch_ned` rồi
   gửi `fly x y` theo **tọa độ tuyệt đối local NED**, x Bắc/y Đông tính bằng
   mét. Chờ HOLD trước đích tiếp; kết thúc bằng `land`, chờ `armed=false`
   và `ON_GROUND` rồi mới `exit`.

5. Sau DISARM, trên máy mô phỏng chạy:

   ```bash
   bash simulation/x500/stop_gazebo.sh --disarmed
   ```

Không dùng `disarm` thay `land`: lệnh đó dừng motor cưỡng bức cả trên không.
Nếu SSH/console rớt trong Offboard, PX4 thực hiện failsafe theo các tham số
đang lưu trên bo; theo dõi tới DISARM/ON_GROUND trước khi dừng Gazebo. Nếu
Pi không thấy dữ liệu dù máy mô phỏng bay bằng PC console trước đây, đó là
vấn đề đường TELEM2/Pi riêng, không chứng minh thuật toán đã hỏng.
