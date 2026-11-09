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
sáu trường hợp lệ trong một payload và Retain OFF. Nó chuyển thành một lệnh `gps_start`: kiểm tra kế
hoạch bằng `gps_plan`, rồi gọi `gps_start`. Từ đất, PX4 TAKEOFF/HOLD trước
khi bay A→B; từ HOLD trên không, nó bắt đầu chặng A→B theo điều kiện của
FSM hiện tại. Kết thúc tại B là HOLD trên không, không tự LAND.

Payload `control` không có `command_id`, hạn dùng hoặc các lệnh pause/LAND.
Cùng payload được khử lặp khi ID của nó còn trong 4096 ID gần nhất của phiên
control service, nhưng chưa có
chống phát lại bền qua reboot.

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

## Các lệnh giám sát ngoài web

MQTT chỉ nhận một payload GPS qua `lac/<deviceID>/control`. Các lệnh
`pause`, `resume`, `cancel`, `return-home`, `return-height`, `land` và
`disarm` không còn topic MQTT; người vận hành dùng `pi/flight/client.py`
qua Unix socket cục bộ. `disarm` là dừng motor khẩn cấp và có thể làm UAV
rơi, không dùng thay LAND.

`return_home` là Mission do Pi tạo tới GPS cất cánh; nó không gọi PX4 RTL.
Sai số estimator tối đa 10 cm (và không quá vertical arrival tolerance) quanh
`MIS_TAKEOFF_ALT` được kẹp lên đúng mức tối thiểu khi tạo Return Home; độ cao
thấp hơn ngưỡng này vẫn bị từ chối để tránh một lần leo cao ngoài dự kiến.
Các lệnh còn phải qua điều kiện phase, GPS mới, health, độ cao/tốc độ và
giới hạn chặng trong `GpsMissionControl`. Mặc định hiện tại: chặng hiện tại→A
và A→B tối đa 10 m, độ cao GPS tối đa 3 m, tốc độ GPS tối đa 0,5 m/s và
không vượt `MPC_XY_VEL_MAX` trên PX4. Có thể đổi giới hạn khi khởi động
flight service, nhưng không tự ý áp giá trị mô phỏng cho UAV thật.

## Trạng thái và nhật ký

Service chỉ subscribe `lac/<deviceID>/control`; nó không publish ACK, state,
health, event hay availability lên MQTT. Xem `status` qua
`pi/flight/client.py`, log JSONL ở `--log-dir`, QGC Messages và ULog PX4.
Do không có topic phản hồi, web không thể xác nhận lệnh đã được nhận hay bay
đến B chỉ bằng MQTT. Log `COMMAND_ACCEPTED` xác nhận flight service nhận
yêu cầu; vị trí/phase mới xác nhận chuyến bay.

Nếu MQTT Explorer còn hiện `state`, `health` hoặc `availability`, đó có thể
là bản tin retained của phiên cũ. Sau khi dừng service cũ, xóa retained
message của đúng ba topic đó trên broker rồi kết nối lại MQTT Explorer;
`ack`/`event` không retained sẽ hết khỏi cây sau khi kết nối lại. Không xóa
`control` và luôn gửi lệnh bay với Retain OFF. Nếu các topic cũ xuất hiện lại,
vẫn còn một bản service cũ đang chạy ở máy khác.

Backend hiện gửi payload `control`; hai service mới qua
unit test, chưa qua smoke test Web → MQTT → Gazebo/Pixhawk. Cách chạy thử và
lệnh LAND cục bộ: [PI_SERVICES.md](PI_SERVICES.md). Đường MQTT chỉ đọc để
kiểm tra payload vẫn có trong [`monitor.py`](../pi/control/monitor.py).
