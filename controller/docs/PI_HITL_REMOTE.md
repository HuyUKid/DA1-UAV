# HITL: mô phỏng trên PC, service điều khiển trên Raspberry Pi

```text
Web → MQTT → Pi/control service → Pi/flight service → TELEM2 Pixhawk
                                                   Pixhawk USB ↔ PC/Gazebo X500
```

Hướng dẫn này áp dụng khi Pi nối Pixhawk qua TELEM2; PC mô phỏng giữ USB.
Web ra lệnh GPS A→B; terminal kỹ thuật `flight/client.py` có thêm NED/GPS.
Pi Flight Service là tiến trình duy nhất mở UART MAVLink. Không mở
`pi/console.py` trực tiếp song song trên cùng UART.

## Chuẩn bị

1. Nạp tham số X500 HITL trên Pixhawk qua QGC theo [SETUP](../../simulation/docs/SETUP.md),
   reboot và xác nhận `SYS_HITL=1`, DISARM, ON_GROUND. Tháo cánh khi thử HITL.
2. Nối TELEM2 TX→Pi RX, RX→Pi TX, GND↔GND và bảo đảm mức logic phù hợp.
   Cổng Pi/baud phải trùng cấu hình Pixhawk; ví dụ thử trước là
   `serial:///dev/ttyAMA0:921600` trên GPIO14/15.
3. Kiểm tra trên Pi trước khi chọn cổng:

   ```bash
   ls -l /dev/serial0 /dev/ttyAMA0 /dev/ttyAMA10 2>/dev/null
   readlink -f /dev/serial0
   cat /proc/cmdline
   pinctrl get 14 15
   id -nG
   ```

   Trên Pi 5, `/dev/serial0` có thể trỏ tới UART debug thay vì GPIO14/15.
   Chỉ dùng `/dev/ttyAMA0` nếu đã xác minh đúng chân và serial login không
   chiếm UART này. User chạy service cần thuộc nhóm `dialout`.

4. Chép `controller/` từ repository hiện tại sang Pi khi Pixhawk đã DISARM.
   Từ máy PC, ví dụ:

   ```bash
   ssh pi@192.168.50.1 'mkdir -p ~/uav-gps'
   rsync -av --exclude='.venv/' --exclude='__pycache__/' \
     --exclude='session-logs/' controller/ \
     pi@192.168.50.1:~/uav-gps/
   ```

5. Trên Pi:

   ```bash
   cd ~/uav-gps
   # Giữ venv đã có, kể cả symlink; chỉ tạo khi đường dẫn hoàn toàn chưa tồn tại.
   if [ ! -e .venv ] && [ ! -L .venv ]; then python3 -m venv .venv; fi
   test -x .venv/bin/python
   readlink -f .venv
   .venv/bin/python -m pip install -r pi/flight/requirements.txt -r pi/control/requirements.txt
   .venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -q
   ```

Nếu wheel `mavsdk` ARM64 không import được native library, dùng
[`build_mavsdk_pi.sh`](../tools/build_mavsdk_pi.sh) theo hướng dẫn trong
[FLIGHT_STATES.md](../../docs/FLIGHT_STATES.md#native-mavsdk-trên-pi).
Unit test không chứng minh UART hoặc bài bay đã đạt.

## Chạy mô phỏng và Pi

Trên PC, mở Gazebo trước:

```bash
PX4_HOME_LAT=47.397742 PX4_HOME_LON=8.545594 PX4_HOME_ALT=488 \
simulation/.venv/bin/python simulation/x500/launch.py --serial auto
```

QGC có thể mở qua UDP sau Gazebo; không để QGC chiếm USB Pixhawk mà
simulator đang giữ. Trên Pi, terminal 1 mở flight service (lệnh dưới có
quyền bay, chỉ dùng trong bài HITL có giám sát):

```bash
cd ~/uav-gps
.venv/bin/python pi/flight/service.py --profile hitl \
  --connection serial:///dev/ttyAMA0:921600 --height 2 \
  --gps-max-height 3 --gps-max-speed 0.5 \
  --socket /tmp/uav-flight.sock --enable-actuation
```

Thay `/dev/ttyAMA0` bằng đúng UART đã kiểm tra. Ở terminal 2 trên Pi,
control service giữ MQTT và hỏi mật khẩu:

```bash
cd ~/uav-gps
.venv/bin/python pi/control/service.py --device-id uav01 \
  --username MQTT_USER --flight-socket /tmp/uav-flight.sock
```

Trước khi nhấn nút web, ở terminal thứ ba mở client kỹ thuật qua IPC:

```bash
cd ~/uav-gps
.venv/bin/python pi/flight/client.py
```

Tại `UAV-REMOTE>` gõ `status` để kiểm tra trước. Sau đó có thể dùng `arm`,
`takeoff`, `fly x y`,
`gps-plan A_lat A_lon B_lat B_lon height speed`, `gps-start`, cùng các lệnh
`pause`, `resume`, `cancel`, `return-home`, `return-height`, `land`.
Chỉ terminal kỹ thuật có `arm`, `takeoff`, `fly x y`; web không nhận chúng.
Khi cần hạ cánh: gõ `land` trong client. Chờ QGC
và `status` xác nhận ON_GROUND, disarmed; lúc đó mới dừng Gazebo. Tránh
gửi `disarm` cưỡng bức thay LAND. Luồng hai service chưa được thử
end to end trên đúng PC/Pi/Pixhawk. Xem [PI_SERVICES.md](PI_SERVICES.md) về cách
xem trạng thái và log.
