# Đối chiếu log bay ngày 10/11/2026

Nguồn: năm ULog trong `logs/2026-11-10/` và log Pi cùng ngày. Đây là các
chuyến bay thật (`SYS_HITL=0`), không phải kết quả HITL của bản sửa.

## Kết luận từ log

- 19:42:14, kế hoạch GPS A→B khoảng 11,05 m bị bản Pi cũ chặn bởi
  `max_leg_m=10`. Các kế hoạch khác lúc 19:47 và 19:58 bị chặn cùng lý do.
  Web cũng bị chặn bởi giới hạn cũ này. Mã hiện tại để giới hạn quãng đường
  mặc định `None`; nếu truyền `--gps-max-leg`, giới hạn lại có hiệu lực.
- 19:43:28, `return-home` bị bản Pi cũ từ chối vì độ cao tương đối
  `-1,68 m < MIS_TAKEOFF_ALT 2,5 m`. ULog cùng thời điểm cho thấy độ cao
  local trên điểm cất cánh khoảng **2,53 m**. Lúc 19:45:54, tình huống
  tương tự: độ cao tương đối khoảng **1,42 m**, local khoảng **2,50 m**.
  Vì vậy ngưỡng `MIS_TAKEOFF_ALT` trên giá trị tương đối không đo đúng
  độ cao bay trong hai lần từ chối này.
- ULog cho thấy PX4 sửa độ cao Home nhiều lần sau khi cất cánh. Ví dụ
  chuyến kết thúc 19:43:50: Home từ 12,10 m nhảy lên 17,33 m gần
  19:42:05; lúc 19:43:28 Home khoảng 16,32 m trong khi độ cao tuyệt đối
  ước lượng khoảng 14,64 m. Do đó `relative_altitude_m` âm dù UAV đang
  ở trên điểm cất cánh theo local NED. Các bộ đếm reset độ cao local/global
  không tăng trong đoạn này. Đây là **điều chỉnh Home**, không có bằng chứng
  EKF reset độ cao. [Mã PX4 của đúng firmware ghi trong ULog](https://github.com/PX4/PX4-Autopilot/blob/d6f12ad1c4f70ad3230afd7d86e971421e02fef4/src/modules/commander/HomePosition.cpp#L327-L355)
  có nhánh sửa Home theo chênh lệch GNSS/baro trong khoảng đầu sau takeoff.
- 20:08:27, kế hoạch GPS ngắn đã bắt đầu; PX4 chuyển Mission và UAV có
  di chuyển. Người vận hành gửi `land` lúc 20:09:06 trước khi có xác nhận
  đến B. Không thể kết luận thuật toán hoàn thành B từ chuyến này.
- Không thấy lệnh `return-height` trong log Pi **ngày 10/11**. Không có
  bằng chứng từ ngày này rằng lệnh đó bị từ chối hay chạy sai.

## Sửa trong mã hiện tại

`flight/gps_mission.py` dùng MAVSDK MissionRaw và waypoint
`MAV_FRAME_GLOBAL_INT` (độ cao tuyệt đối MSL) thay cho waypoint độ cao
tương đối Home. Mục tiêu độ cao được tính bằng:

`độ cao tuyệt đối hiện tại + độ cao mong muốn trên launch - độ cao local hiện tại trên launch`.

Lệnh `return-home` giữ độ cao local đang bay và đi tới GPS ghi khi TAKEOFF;
`return-height` tiếp tục dùng local NED để đổi độ cao tại x/y hiện tại.
Khi Home thay đổi, waypoint tuyệt đối đã tải lên không bị dịch theo Home.
Pi vẫn yêu cầu telemetry mới, HOLD và xác nhận vị trí/độ cao trước khi báo
hoàn tất. `DO_CHANGE_SPEED` trong mission mang tốc độ được yêu cầu.

Kiểm thử đơn vị bao gồm trường hợp thực tế `relative_altitude_m=-1,68`
với local height `2,5 m`. Bài thử HITL trực tiếp ngày 11/11 xác nhận PX4
nhận MissionRaw, đi A→B, return-home và LAND; xem
[`GPS_HITL_2026-11-11.md`](GPS_HITL_2026-11-11.md). Bài thử đó không thay
thế việc kiểm tra ULog, pause/resume và bay thật với bản sửa.
