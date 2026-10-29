# Kiểm chứng thuật toán trên X500 Classic HITL — 26/10/2026

## Phạm vi và cấu hình

Pixhawk FMUv6C chạy PX4 1.17.0, `SYS_HITL=1`, nối USB với Gazebo Classic 11.10.2 trên Ubuntu 22.04.5. Console Python của dự án dùng UDP loopback `127.0.0.1:14540` với MAVSDK kiểu ground station. Không điều khiển Pi; cánh đã tháo. Model X500 port sang Classic nặng khoảng 2,0893 kg. Bài bay ở world phẳng, không có gió hay chướng ngại; độ cao đặt 2 m, đích dịch 1 m Bắc + 1 m Đông theo hệ local NED rồi quay về mốc. Đo pose thật của model Gazebo, đồng thời lấy vị trí/tốc độ PX4 và ULog. Các bài thử giữ `controller/pi/flight/offboard_control.py` làm thuật toán điều khiển mục tiêu, PX4 làm vòng điều khiển bay.

Dữ liệu rút gọn có thể đọc trong [JSON so sánh](data/algorithm_comparison_2026-10-26.json); [pose và telemetry để vẽ lại](data/algorithm_traces_2026-10-26.json) cũng được đưa vào Git. [Đồ thị](assets/algorithm_comparison_2026-10-26.png) thể hiện chuyến bay hoàn chỉnh đầu tiên của mỗi cấu hình. Nếu đã cài `matplotlib`, tạo lại bằng `python3 simulation/tools/plot_algorithm_validation.py simulation/docs/data/algorithm_traces_2026-10-26.json simulation/docs/assets/algorithm_comparison_2026-10-26.png`. Log thô và mẫu pose của phiên ở `simulation/artifacts/algorithm-20261026/` trên máy này, được bỏ qua bởi Git. JSON rút gọn ghi SHA-256 của từng `report.json`; giữ nguyên log thô, không sửa số đo để khớp kết luận.

## Kết quả bay

| Cấu hình | Chuyến thường | Tốc độ XY đỉnh (ước lượng PX4) | Sai số XY RMS khi HOLD (pose Gazebo) | Sai số độ cao RMS khi HOLD | Nghiêng model đỉnh |
|---|---:|---:|---:|---:|---:|
| PX4 mặc định sau reset, hover 0,5 | 1 | 1,020 m/s | 0,060 m | 0,073 m | 9,81° |
| Giới hạn 0,5 m/s, hover 0,5 | 2 liên tiếp | 0,527 / 0,530 m/s | 0,058 / 0,057 m | 0,014 / 0,010 m | 11,97° / 4,54° |
| **Bộ chọn: giới hạn 0,5 m/s, hover 0,74** | 1; thêm 2 bài khẩn cấp | **0,531 m/s** | **0,055 m** | **0,019 m** | **2,90°** |

Với bộ chọn, sai số XY phân vị 95% lúc HOLD là 0,077 m; sai số độ cao tuyệt đối phân vị 95% là 0,028 m; tốc độ ngang phân vị 95% lúc HOLD là 0,029 m/s. Ba đoạn HOLD của chuyến thường có độ dịch đầu-cuối lần lượt 0,059 m, 0,024 m, 0,004 m. Như vậy có trôi nhỏ, không phải giữ tọa độ tuyệt đối. Đồ thị cho thấy đường tới đích và quay về êm trong world thử, không có mất ổn định hay trượt lớn ở các khoảng bay ngắn này. Các mẫu baseline/limited được lấy thưa bằng lệnh `gz model`; mẫu bộ chọn lấy từ pose topic dày hơn, nên các cực trị và độ mượt nhìn bằng đồ thị không hoàn toàn có cùng tần suất lấy mẫu.

Ở mọi chuyến thường hoàn thành, thuật toán đã TAKEOFF, chờ xác nhận HOLD, chọn FLY, tới đích, quay về, LAND, xác nhận ON_GROUND/DISARM. Lệnh FLY khi đang TAKEOFF hoặc FLY và tọa độ trần trong HOLD bị từ chối đúng trạng thái. Hai chuyến liên tiếp ở cấu hình giới hạn chứng minh có thể LAND rồi ARM lại trong cùng phiên controller. Với bộ chọn, LAND được chấp nhận khi TAKEOFF còn khóa đích, sau đó hạ cánh và DISARM. Bài thứ ba ngừng luồng setpoint Offboard có chủ ý; PX4 vào LAND sau khoảng 1,22 s và tự DISARM; controller chuyển EXTERNAL, không tự giành lại Offboard. Đây là kiểm tra một kiểu mất luồng setpoint trong HITL, không thay thế đánh giá toàn bộ failsafe bay thật.

ULog của ba bài bộ chọn trên Pixhawk: `sess104/log102.ulg`, `log103.ulg`, `log104.ulg` (lưu cục bộ trong `simulation/artifacts/algorithm-20261026/ulogs/sess104/`). Chúng xác nhận `SYS_HITL=1`, `MPC_THR_HOVER=0,74`, `MPC_XY_VEL_MAX=0,5`, `MPC_TKO_SPEED=0,4`, `COM_OF_LOSS_T=0,5`, `COM_OBL_RC_ACT=4`, `COM_RC_IN_MODE=4`. ULog chuyến thường cho hover thrust estimate median 0,734, nằm gần giá trị 0,74 của **model**. SHA-256 tương ứng: `log102` b637b840cfb5e29b58938023e8e2cdbb9b0b6b156225fa1ecd2e8a7f5dbfb02b; `log103` e621c4bc3e00f40b67080dd209bac757031104f70537ec946aec825401e0bda6; `log104` 7baa87eda43c2a93133b52fd7ce97a17e5cdc12e7296321374379da46d0669d6.

## Bộ tham số được xuất

- [X500 HITL](../params/x500_hitl.params): Quad-X HIL, USB/Gazebo, TELEM2, terminal PC không có RC, giới hạn XY 0,5 m/s, takeoff 0,4 m/s, lên/xuống 0,5 m/s, LAND 0,3 m/s, gia tốc và jerk 2, hover 0,74, Offboard loss 0,5 s → LAND. Các breaker nguồn/safety chỉ dành cho HITL. Sau import phải reboot và kiểm tra lại tham số/arming bằng QGC.
- [UAV thật](../../controller/params/hardware.params): overlay **ứng viên**, `SYS_HITL=0`, generic Quad-X `SYS_AUTOSTART=4001` như quan sát trước reset, các giới hạn chuyển động chậm giống trên, TELEM2, RC/joystick và pin 6S. Xóa HIL actuator mapping và bật lại kiểm tra supply/safety. Không đưa hover 0,74, PID của model hay cách xử lý Offboard loss của HITL sang đây. Chưa nạp lên Pixhawk và chưa thử bay thật.

Bộ cũ người dùng gửi ghi tốc độ XY 0,6 m/s, hạ 0,6 m/s và flow control tự động (`MAV_1_FLOW_CTRL=2`). Bộ mới dùng 0,5 m/s cho cả hai trục để bay chậm hơn; `FLOW_CTRL=0` phù hợp dây TELEM2 TX/RX/GND hiện mô tả. Giữ takeoff 0,4, LAND 0,3 và hover 0,74 **chỉ với model**. Giá trị `MPC_{XY,Z}_VEL_ALL=-1` giữ các giới hạn riêng lẻ có hiệu lực theo [tham chiếu PX4 v1.17](https://docs.px4.io/v1.17/en/advanced_config/parameter_reference). Đây là file QGC tham số một phần, không phải bản sao toàn bộ cấu hình.

UAV thật khoảng 5–6 kg, 6S, motor 3120-700 kV và cánh ghi “12.45” (cỡ/độ bước chưa xác nhận). Model X500 chỉ khoảng 2,0893 kg. Không thể suy ra hover thrust, PID, lực tối đa, độ an toàn motor/ESC hoặc độ mượt bay thật từ các bài bay này. Trước khi chuyển sang bay thật cần xác minh khung và mapping motor, chiều quay, ESC, hiệu chuẩn IMU/compass/radio, pin/giám sát điện, failsafe RC/GCS/Offboard và hover/đáp ứng thực địa trên chính UAV. File thật không thay thế backup cấu hình bay thật. Chi tiết phiên reset và giới hạn backup trước reset được giữ cục bộ tại `simulation/artifacts/SESSION_2026-10-26.md` trên máy thử; artifacts bị Git ignore nên không có trong bản clone. Bản backup trực tiếp trước reset không hợp lệ và không được coi là cấu hình bay thật có thể phục hồi; chỉ khôi phục được tham số lịch sử từ ULog trước đó.

Các chuyến thất bại ban đầu và một lần timeout do harness cũng được giữ trong artifacts, không tính là chuyến đạt. Sau thử nghiệm, Pixhawk báo HITL/DISARM/ON_GROUND; Gazebo đã dừng. Pixhawk vẫn ở cấu hình HITL, không ở cấu hình bay thật.
