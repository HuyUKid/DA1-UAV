# HITL: mô phỏng trên PC, service điều khiển trên Raspberry Pi

```text
Web → MQTT → Pi/control service → Pi/flight service → TELEM2 Pixhawk
                                                   Pixhawk USB ↔ PC/Gazebo X500
```

Hướng dẫn này áp dụng khi Pi nối Pixhawk qua TELEM2; PC mô phỏng giữ USB.
Web là luồng ra lệnh GPS A→B. Pi flight service là tiến trình duy nhất mở
UART MAVLink. Console `fly x y` chỉ dùng cho thử kỹ thuật riêng, không chạy
song song với flight service trên cùng UART.

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
   ssh pi@192.168.50.1 'mkdir -p ~/uav/current/controller'
   rsync -av --exclude='.venv/' --exclude='__pycache__/' \
     --exclude='session-logs/' controller/ \
     pi@192.168.50.1:~/uav/current/controller/
   ```

5. Trên Pi:

   ```bash
   cd ~/uav/current/controller
   python3 -m venv .venv
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
cd ~/uav/current/controller
.venv/bin/python pi/flight/service.py --profile hitl \
  --connection serial:///dev/ttyAMA0:921600 --height 2.5 \
  --gps-max-height 3 --gps-max-speed 0.5 \
  --socket /tmp/uav-flight.sock --enable-actuation
```

Thay `/dev/ttyAMA0` bằng đúng UART đã kiểm tra. Ở terminal 2 trên Pi,
control service giữ MQTT và hỏi mật khẩu:

```bash
cd ~/uav/current/controller
.venv/bin/python pi/control/service.py --device-id uav01 \
  --username MQTT_USER --flight-socket /tmp/uav-flight.sock \
  --allow-legacy-start
```

Trước khi nhấn nút web, ở terminal thứ ba kiểm tra lệnh đọc và đường
LAND cục bộ qua IPC:

```bash
cd ~/uav/current/controller
.venv/bin/python pi/flight/client.py status
```

Khi cần hạ cánh: `.venv/bin/python pi/flight/client.py land`. Chờ QGC
và `status` xác nhận ON_GROUND, disarmed; lúc đó mới dừng Gazebo. Tránh
gửi `disarm` cưỡng bức thay LAND. Luồng hai service mới chưa được thử
end to end trên đúng PC/Pi/Pixhawk; bài HITL qua console trước đây không
xác nhận đường MQTT/IPC mới. Xem [PI_SERVICES.md](PI_SERVICES.md) về topic
ACK, trạng thái và log.
