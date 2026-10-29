# Nhiệm vụ GPS A→B từ web

Luồng chính: web/backend gửi MQTT, [control service](../pi/control/service.py)
kiểm tra lệnh, [flight service](../pi/flight/service.py) gọi
[`GpsMissionControl`](../pi/flight/gps_mission.py) trên một kết nối MAVSDK với PX4.
Tọa độ web là vĩ độ/kinh độ. Lệnh `fly x y` của console dùng mét local NED
và không thuộc giao thức web.

## Payload web hiện tại

Backend hiện gửi sáu trường cùng trong **một** bản tin tới
`lac/<deviceID>/control` khi bấm “Gửi nhiệm vụ & cất cánh”:

```text
c:spd:0.5;c:height:3;c:startlat:47.3977760;c:startlong:8.5456050;c:endlat:47.3978100;c:endlong:8.5456500;
```

`startlat/startlong` là điểm A, `endlat/endlong` là điểm B. `height` là
độ cao so với mốc cất cánh; `spd` là m/s. Control service chỉ nhận đúng
sáu trường hợp lệ trong một payload, Retain OFF và phải được bật rõ
`--allow-legacy-start`. Nó chuyển thành một lệnh `gps_start`: kiểm tra kế
hoạch bằng `gps_plan`, rồi gọi `gps_start`. Từ đất, PX4 TAKEOFF/HOLD trước
khi bay A→B; từ HOLD trên không, nó bắt đầu chặng A→B theo điều kiện của
FSM hiện tại. Kết thúc tại B là HOLD trên không, không tự LAND.

Payload legacy không có `command_id`, hạn dùng hoặc các lệnh pause/LAND.
Cùng payload được khử lặp khi ID của nó còn trong 4096 ID gần nhất của phiên
control service, nhưng chưa có
chống phát lại bền qua reboot. Do đó cờ legacy là đường thử có kiểm soát,
không phải giao thức hoàn chỉnh cho UAV thật.

### Bay thẳng đứng tại chỗ

Nếu A và B trùng nhau trong `xy_tolerance` (mặc định 0,5 m), đồng thời nằm
trong bán kính `start_error_m` (mặc định 5 m) quanh vị trí GPS mới nhất
của PX4, Flight Service hiểu đây là nhiệm vụ `vertical_only`: nó ghim một
waypoint vào chính vị trí GPS mới nhất, thay đổi tới `height`, rồi HOLD mà
không chủ ý dịch chuyển ngang. Ví dụ với Home mô phỏng hiện tại:

```text
c:spd:0.5;c:height:3;c:startlat:47.397742;c:startlong:8.545594;c:endlat:47.397742;c:endlong:8.545594;
```

A=B nhưng ở ngoài bán kính đó vẫn bị từ chối; hệ thống không tự biến một
điểm ở xa thành lệnh bay thẳng đứng. GPS/estimator vẫn có thể dao động nhỏ,
nên “giữ nguyên” được xác nhận theo tolerance chứ không phải sai số tuyệt đối
bằng 0. Trường `gps_mission.plan.vertical_only=true` trong status xác nhận
kế hoạch đã được phân loại đúng.

## Giao thức v2 cho các nút điều khiển

Topic nhận là `lac/<deviceID>/v2/command`. Mỗi bản tin JSON có `schema=2`,
`command_id` duy nhất, `mission_id`, `issued_at_utc`, `expires_at_utc`,
`type` và `params`. Ví dụ cấu trúc (thời gian cần tạo mới cho mỗi lần gửi):

```json
{
  "schema": 2,
  "command_id": "cmd-001",
  "mission_id": "mission-001",
  "issued_at_utc": "2026-10-29T02:00:00Z",
  "expires_at_utc": "2026-10-29T02:00:10Z",
  "type": "gps_start",
  "params": {
    "a": {"lat_deg": 47.397776, "lon_deg": 8.545605},
    "b": {"lat_deg": 47.397810, "lon_deg": 8.545650},
    "height_above_launch_m": 3.0,
    "speed_m_s": 0.5
  }
}
```

| `type` | Hành động ở flight service | Kết quả phải quan sát tiếp |
|---|---|---|
| `gps_start` | `gps_plan` rồi `gps_start` | TAKEOFF → MISSION → GPS_COMPLETE/HOLD |
| `pause` / `resume` | Dừng/tiếp tục mục tiêu đang hoạt động | PX4 HOLD/MISSION hoặc OFFBOARD đúng phase |
| `cancel` | Bỏ mục tiêu và yêu cầu HOLD | HOLD tại chỗ; không LAND |
| `return_home` | Về GPS đã lưu lúc TAKEOFF ở độ cao hiện tại | HOME_COMPLETE/HOLD; LAND riêng |
| `return_height` | Về độ cao TAKEOFF tại vị trí ngang hiện tại | HOLD đúng độ cao; LAND riêng |
| `land` | Yêu cầu PX4 LAND | LAND, sau đó ON_GROUND và disarmed |
| `disarm` | Dừng motor cưỡng bức | Bắt buộc `params.confirm_force=true`; có thể làm UAV rơi |

`return_home` là Mission do Pi tạo tới GPS cất cánh; nó không gọi PX4 RTL.
Sai số estimator tối đa 10 cm (và không quá vertical arrival tolerance) quanh
`MIS_TAKEOFF_ALT` được kẹp lên đúng mức tối thiểu khi tạo Return Home; độ cao
thấp hơn ngưỡng này vẫn bị từ chối để tránh một lần leo cao ngoài dự kiến.
Các lệnh còn phải qua điều kiện phase, GPS mới, health, độ cao/tốc độ và
giới hạn chặng trong `GpsMissionControl`. Mặc định hiện tại: chặng hiện tại→A
và A→B tối đa 10 m, độ cao GPS tối đa 3 m, tốc độ GPS tối đa 0,5 m/s và
không vượt `MPC_XY_VEL_MAX` trên PX4. Có thể đổi giới hạn khi khởi động
flight service, nhưng không tự ý áp giá trị mô phỏng cho UAV thật.

## ACK, trạng thái và nhật ký

Control service xuất `lac/<deviceID>/v2/ack`, `/state`, `/health` và
`/availability`. ACK `received` nghĩa là đã nhận payload; `accepted` nghĩa
là flight service đã nhận yêu cầu. **Chỉ status mới cho biết phase và
telemetry hiện tại**; cả hai ACK đều không có nghĩa đã bay tới B hoặc hạ
cánh. Log JSONL ở `--log-dir` giữ sự kiện lệnh và trạng thái trên máy chạy.
QGC Messages và ULog PX4 là nguồn khác.

Backend hiện mới được quan sát gửi payload legacy; chưa có bằng chứng nó
publish command v2 hoặc subscribe các topic ACK/state. Hai service mới qua
unit test, chưa qua smoke test Web → MQTT → Gazebo/Pixhawk. Cách chạy thử và
lệnh LAND cục bộ: [PI_SERVICES.md](PI_SERVICES.md). Đường MQTT chỉ đọc để
kiểm tra payload vẫn có trong [`monitor.py`](../pi/control/monitor.py).
