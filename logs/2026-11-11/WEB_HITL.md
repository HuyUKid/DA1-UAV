# Kiểm tra lệnh web qua MQTT trong HITL — 11/11/2026

Nguồn: `session-logs/services/control-20261111T120857.554074Z.jsonl` và
`session-logs/services/flight-20261111T120835.628303Z.jsonl` trên PC thử.
Pixhawk chạy `SYS_HITL=1`; Gazebo giữ USB; Flight Service nối UDP cục bộ.
Đây là kiểm tra Web/MQTT trên PC, **chưa phải kiểm tra đường Pi→TELEM2**.

## Điều log xác nhận

- Control Service kết nối broker và nhận `gps_start` từ topic `control`.
  Lúc 12:11:21 UTC, lệnh được nhận; 12:11:23 UTC được Flight Service chấp
  nhận. PX4 chuyển `MISSION`, sau đó `GPS_COMPLETE`/`HOLD`.
- `return_home` được Flight Service chấp nhận lúc 12:11:55 UTC và đạt
  `HOME_COMPLETE` lúc 12:12:01 UTC. Một lượt về Home khác lúc 12:13:33 UTC
  đạt `HOME_COMPLETE` lúc 12:13:39 UTC.
- `land` lúc 12:12:32 UTC và 12:13:41 UTC đều được chấp nhận. Sau mỗi lần,
  trạng thái chuyển về `IDLE`, `ON_GROUND`, `armed=false`.
- Lệnh `pause` và `resume` qua MQTT cũng được chấp nhận trong một lượt
  `FLY` local NED đang chạy (12:13:17–12:13:28 UTC), rồi `cancel` và
  `return_home` thành công. Việc này kiểm tra nút web và IPC, nhưng không
  chứng minh pause/resume của **GPS Mission** đã hoạt động.

## Lệnh bị từ chối đúng điều kiện trạng thái

- Một `gps_start` thứ hai lúc 12:11:26 UTC bị từ chối vì nhiệm vụ đầu chưa
  đến HOLD xác nhận.
- `pause` lúc 12:12:16 UTC và `resume` lúc 12:12:26 UTC bị từ chối vì
  nhiệm vụ GPS đã kết thúc; không có nhiệm vụ đang tạm dừng để tiếp tục.
- `cancel` lúc 12:12:37 UTC bị từ chối khi PX4 đã LANDING.
- Một `takeoff` local lúc 12:09:28 UTC bị từ chối vì lần LAND trước chưa
  trở về `IDLE`, `armed=false`.

Các bản tin `COMMAND_ACCEPTED` chỉ xác nhận service xử lý lệnh; kết luận
đến đích/hạ cánh dựa trên `FLIGHT_STATE_CHANGED`. Sau bài thử, truy vấn
trực tiếp Flight Service cũng trả `IDLE`, `ON_GROUND`, `armed=false`,
`last_error=null`. Chưa có ULog PX4 của các lượt này trong báo cáo; vị trí
và chuyển động vật lý chưa được đối chiếu độc lập.
