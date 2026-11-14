# Nhiệm vụ GPS A→B từ web

Luồng chính: web/backend gửi MQTT, [control service](../pi/control/service.py)
kiểm tra lệnh, [flight service](../pi/flight/service.py) gọi
[`GpsMissionControl`](../pi/flight/gps_mission.py) trên một kết nối MAVSDK với PX4.
Tọa độ web là vĩ độ/kinh độ. Lệnh `fly x y` của terminal kỹ thuật
`flight/client.py` dùng mét local NED và không thuộc giao thức web.

## Payload web hiện tại

Backend hiện gửi sáu trường cùng trong **một** bản tin tới
`lac/<deviceID>/control` khi bấm “Gửi nhiệm vụ & cất cánh”:

```text
c:spd:0.5;c:height:3;c:startlat:47.3977760;c:startlong:8.5456050;c:endlat:47.3978100;c:endlong:8.5456500;
```

`startlat/startlong` là điểm A, `endlat/endlong` là điểm B. `height` là
độ cao so với mốc cất cánh; `spd` là m/s. Control service chỉ nhận đúng
sáu trường hợp lệ trong một payload và Retain OFF. Nó chuyển thành một lệnh `gps_start`: kiểm tra kế
hoạch bằng `gps_plan`, rồi gọi `gps_start`. Từ đất, PX4 TAKEOFF/HOLD trước
khi bay A→B; từ HOLD trên không, nó bắt đầu chặng A→B theo điều kiện của
FSM hiện tại. Kết thúc tại B là HOLD trên không, không tự LAND.

Payload `control` không có `command_id` hoặc hạn dùng do backend cấp.
Pi tạo ID riêng cho mỗi bản tin nhận được, nên có thể gửi lại cùng một
nhiệm vụ sau khi nhiệm vụ trước hoàn tất. Retain phải OFF; giao thức hiện
không có cơ chế chống phát lại bản tin cũ do backend gửi lại.

Các nút web dùng **cùng topic** `lac/<deviceID>/control`, mỗi lần bấm gửi
một payload riêng: `d:pause` → tạm dừng; `d:resume` → tiếp tục;
`d:abort` → hủy đích hiện tại và HOLD tại chỗ; `d:rtl` → trở về GPS
điểm cất cánh ở độ cao hiện tại rồi HOLD; `d:land` → yêu cầu PX4 LAND.
Không dùng Retain. `d:rtl` yêu cầu nhiệm vụ đang chạy đã hoàn tất hoặc đã
`d:abort` và PX4 xác nhận HOLD; khi GPS đang PAUSED, lệnh này tự hủy
nhiệm vụ cũ rồi kiểm tra HOLD. `d:abort` trong TAKEOFF bị từ chối vì chưa
có chặng GPS để hủy;
`d:land` vẫn là lệnh hạ cánh ưu tiên. Các lệnh chỉ được nhận theo phase và
telemetry hiện hành, không bảo đảm hoàn thành chỉ nhờ ACK MQTT/IPC.

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

## Các lệnh giám sát cục bộ

Terminal `pi/flight/client.py` có thêm `arm`, `takeoff`, `fly x y`,
`gps-plan`, `gps-start`, `return-height`, `disarm` và các lệnh chung
`pause`, `resume`, `cancel`, `return-home`, `land` qua cùng Unix socket.
`return-height`
hiện không có nút web. `disarm` là dừng motor khẩn cấp và có thể làm UAV
rơi, không dùng thay LAND.

`return_home` là Mission do Pi tạo tới GPS cất cánh; nó không gọi PX4 RTL.
Waypoint GPS và về Home dùng MAVLink `MAV_FRAME_GLOBAL_INT` với độ cao
tuyệt đối (AMSL) từ ước lượng PX4 lúc phát lệnh, cộng chênh lệch độ cao
local còn cần đi. Pi gửi `DO_CHANGE_SPEED` trước waypoint. Cách này tránh
việc PX4 điều chỉnh độ cao Home trong khi bay làm dịch độ cao waypoint.
`MIS_TAKEOFF_ALT` (độ cao cất cánh mặc định của PX4) không được dùng làm
ngưỡng tối thiểu cho lệnh về Home. `return-height` dùng Offboard để về độ cao TAKEOFF mặc định
2 m tại x/y hiện tại; nó chỉ báo hoàn thành khi telemetry đạt tolerance.
File overlay thật `controller/params/hardware.params` cũng đặt
`MIS_TAKEOFF_ALT=2.0` cho PX4 native Takeoff; sửa file không tự thay giá trị
trên Pixhawk, cần nạp qua QGC và đọc lại tham số sau reboot.

Mặc định Pi **không giới hạn khoảng cách** hiện tại→A, A→B hoặc quãng về
điểm cất cánh. Tùy chọn `--gps-max-leg` cho phép bật giới hạn khi cần.
Deadline Return Home được tính từ quãng đường GPS tới Home và tốc độ lệnh:
`max(target_timeout_s, 2 × distance_m / speed_m_s + 30 s)`; không còn mốc
60 s cố định cho đường về dài. Đây là hạn giám sát của Pi, không bảo đảm
đủ pin hoặc khả năng bay tới Home.
Ngưỡng 5 m `start_error_m` vẫn kiểm tra UAV không rời khỏi vị trí lúc lập
kế hoạch trước khi bắt đầu. Độ cao nhiệm vụ GPS mặc định từ 2 đến 3 m,
tốc độ 0,1–0,5 m/s và không vượt `MPC_XY_VEL_MAX` trên PX4. Có thể đổi
giới hạn độ cao/tốc độ khi khởi động flight service; PX4 vẫn có geofence,
battery failsafe và các kiểm tra bay riêng.

Phân tích ULog bay thật ngày 10/11 ở
[`FLIGHT_LOG_2026-11-10.md`](FLIGHT_LOG_2026-11-10.md). Bài thử trực tiếp
HITL ngày 11/11 ở [`GPS_HITL_2026-11-11.md`](GPS_HITL_2026-11-11.md):
bay thẳng đứng, A→B 1,5 m, return-home, return-height và LAND đã chạy qua
terminal PC. PX4 đã nhận MissionRaw; app chỉ báo hoàn tất sau khi telemetry
vào bán kính xác nhận. Pause/resume của GPS Mission, đường Pi UART, ULog
của bài thử và bay thật với bản sửa chưa được kiểm chứng. Luồng
Web→MQTT→hai service→HITL trên PC được ghi ở
[`WEB_HITL_2026-11-11.md`](WEB_HITL_2026-11-11.md).

## Trạng thái và nhật ký

Service chỉ subscribe `lac/<deviceID>/control`; nó không publish ACK, state,
health, event hay availability lên MQTT. Xem `status` qua
`pi/flight/client.py`, log JSONL ở `--log-dir`, QGC Messages và ULog PX4.
Do không có topic phản hồi, web không thể xác nhận lệnh đã được nhận hay bay
đến B chỉ bằng MQTT. Log `COMMAND_ACCEPTED` xác nhận flight service nhận
yêu cầu; vị trí/phase mới xác nhận chuyến bay.

Backend hiện gửi payload `control`; hai service đã qua smoke test
Web → MQTT → Gazebo/Pixhawk trên PC. Cách chạy thử và
lệnh LAND cục bộ: [PI_SERVICES.md](PI_SERVICES.md). Đường MQTT chỉ đọc để
kiểm tra payload vẫn có trong [`monitor.py`](../pi/control/monitor.py).
