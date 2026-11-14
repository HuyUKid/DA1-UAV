# Kiểm tra GPS Mission trực tiếp trong HITL — 11/11/2026

Pixhawk FMUv6C chạy `SYS_HITL=1`, Gazebo Classic X500 nhận PX4 qua USB.
Console PC nối `udpin://127.0.0.1:14540`; Pi và MQTT không tham gia bài thử.
Nguồn: `session-logs/pi-20261111T115143.256351Z.log` và
`session-logs/pi-20261111T115809.525406Z.log` trên máy thử.

## Lỗi phát hiện và sửa

- Bản MissionRaw đầu tiên bị MAVSDK trả `CURRENT_INVALID` khi tải mission
  return-home: tất cả item đều có `current=0`. MAVSDK v4.0.6 yêu cầu đúng
  một item `current=1` ([mã MAVSDK v4.0.6](https://github.com/mavlink/MAVSDK/blob/v4.0.6/cpp/src/mavsdk/core/mavlink_mission_transfer_client.cpp)).
  Item `DO_CHANGE_SPEED` đầu tiên hiện được đánh dấu
  `current=1`; waypoint còn lại là `0`.
- Sau khi mission chạy được, log cho thấy trạng thái `GPS_COMPLETE` và
  `HOME_COMPLETE` được gắn khi UAV còn cách đích khoảng 1 m trên chặng
  1,5 m, vì mã dùng bán kính cố định ít nhất 2 m. Bán kính xác nhận hiện là
  `min(2 m, max(xy_tolerance_m, 25% quãng đường))`; mặc định 0,5 m cho
  chặng 1,5 m. Sau khi PX4 báo mission finished và HOLD, app đợi tối đa
  `confirmation_s` để vị trí/độ cao mới đạt ngưỡng rồi mới báo hoàn tất.

## Kết quả bay thử sau khi sửa

1. Trước khi bay: `ON_GROUND`, `armed=false`, `health_all_ok=true`.
2. Kế hoạch A `(47.3977600, 8.5455936)` → B
   `(47.3977735, 8.5455936)`, cao 2,5 m so với launch, tốc độ lệnh
   0,3 m/s. PX4 xác nhận ARM, TAKEOFF, Mission và HOLD.
3. `GPS_COMPLETE` xuất hiện khi GPS còn cách B khoảng **0,345 m**;
   sau đó telemetry tại B `(47.3977735, 8.5455936)`, độ cao local
   **2,506 m** trên launch. `last_error=null`.
4. `return-home` tạo mission mới về GPS launch ở độ cao đang bay.
   `HOME_COMPLETE` xuất hiện khi GPS còn cách Home khoảng **0,334 m**;
   sau đó telemetry `(47.3977599, 8.5455935)`, độ cao local
   **2,504 m**. `return_position_confirmed=true`, `last_error=null`.
5. `land` kết thúc với `ON_GROUND`, `armed=false`; console sau đó thoát.

Bài thử trước cùng ngày cũng hoàn tất bay thẳng đứng tại chỗ lên 3 m,
bay A→B khoảng 1,5 m, return-home, return-height về 2,5 m và LAND.
Giá trị vị trí ở đây là **ước lượng PX4 trong HITL**, không phải đo độc lập
quỹ đạo vật lý. Chưa thử pause/resume, lệnh từ web qua MQTT, Pi UART hoặc
phân tích ULog PX4 cho bản sửa. Không suy ra độ an toàn bay thật từ bài thử
mô phỏng này.
