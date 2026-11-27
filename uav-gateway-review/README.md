# UAV Gateway — telemetry cho web

Điểm vào duy nhất là `telemetry_reading.py`. Gateway nhận MAVLink và gửi
telemetry lên MQTT; không thực hiện lệnh bay. Control Service trong
`controller/pi/control/service.py` nhận lệnh web và chuyển tới Flight Service.

## Chạy trên Pi cùng Flight Service

Router giữ serial Pixhawk và chuyển MAVLink tới hai cổng riêng:

- Flight Service: `127.0.0.1:14540`.
- Gateway: `127.0.0.1:14541`.

Gateway và Flight Service chạy cùng Pi để đọc socket `/tmp/uav-flight.sock`.
Triển khai thư mục này vào `~/uav_gateway_code`; giữ venv và config MQTT đã có.

```bash
cd ~/uav_gateway_code
bash run_laptop.sh uav01
```

Tên script được giữ để tương thích; mặc định dùng UDP 14541. Đối số thứ
hai cho phép chọn kết nối khác, ví dụ:

```bash
bash run_laptop.sh uav01 udpin:127.0.0.1:14541
```

Script chuẩn bị venv, cài dependency, tạo config từ `mqtt.example.json` nếu
chưa có, hỏi mật khẩu và chạy gateway. Không mở thêm reader cùng cổng/ID.
Chạy thủ công sau khi đã có môi trường:

```bash
read -rsp 'Mat khau MQTT: ' MQTT_PASSWORD
echo
export MQTT_PASSWORD
.venv/bin/python -u telemetry_reading.py \
  --connection udpin:127.0.0.1:14541 \
  --uav-id uav01 --request-streams --interval 1 \
  --mqtt-config mqtt.remote.json --output reports/status.json --quiet
```

`--interval 1` xuất mỗi giây; mặc định của reader là 2 giây. Config không
chứa mật khẩu, chỉ tên biến môi trường `MQTT_PASSWORD`. Không đưa mật khẩu
vào repository. MQTT_HOST, MQTT_PORT và MQTT_USERNAME có thể ghi đè qua môi trường.

## Telemetry và độ cao

- `lac/uav01/data`: dữ liệu TAB, mã trường từ `fields.json`, QoS 0, retain OFF.
- `lac/uav01/control`: gateway chỉ theo dõi/ghi log; không thực thi.
- `lac/uav01/debug`: chẩn đoán theo cấu hình; `debug_interval_s=0` tắt bản tin định kỳ.
- `reports/status.json`: snapshot JSON tại máy; `--jsonl` bật lịch sử nếu cần.

Bộ mã hóa trong `lac_protocol.py` tạo timestamp UTC dạng YYYYMMDDhhmmssSSS,
trường TYPE:1, sau đó các cặp CODE:value phân cách bằng TAB. Chỉ các trường
đã có trong `fields.json` được gửi; dữ liệu không biết được bỏ qua.

Reader mới ưu tiên độ cao `height_above_launch_m` từ Flight Service để ghi
vào `altitude_relative` (code 28). Khi thiếu số đo hợp lệ, nó quay lại độ cao
so với Home PX4. Hai mốc dùng chung mã, nên web chưa phân biệt được nguồn;
đây không phải số đo AGL. Thuật toán reader được giữ nguyên từ bản Pi.

## Mẫu systemd và kiểm tra

`systemd/uav-telemetry.service` dùng `/home/pi/uav_gateway_code`, UDP 14541
và file môi trường `/etc/uav/telemetry.env`. Chỉ dùng nếu đường dẫn và môi
trường khớp máy triển khai; không chạy cùng gateway thủ công.

```bash
.venv/bin/python -B -m unittest test_reader -v
```

Bài kiểm tra reader dùng dữ liệu giả, không đọc socket Flight Service thật
và không xác nhận broker/web thực tế.
Quy trình HITL qua Pi nằm trong [SETUP.md](../simulation/docs/SETUP.md#chạy-mô-phỏng-và-pi).
