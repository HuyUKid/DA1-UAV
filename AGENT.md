# Hướng dẫn làm việc với dự án UAV

Tài liệu này hướng dẫn người hoặc agent sửa mã nguồn, kiểm thử và cập nhật
tài liệu trong repository. Thực hiện theo yêu cầu hiện tại của người dùng;
các quy ước dưới đây mô tả cấu trúc và hành vi đang dùng của dự án.

## Đọc trước khi thay đổi

- [README.md](README.md): kiến trúc, triển khai Pi và lệnh vận hành.
- [FLIGHT_STATES.md](docs/FLIGHT_STATES.md): FSM, điều kiện chuyển trạng thái,
  ACK, timeout và các trường status.
- [SETUP.md](simulation/docs/SETUP.md): model X500, nguồn upstream và quy trình
  cài/chạy mô phỏng trên PC riêng.
- Báo cáo trong `logs/YYYY-MM-DD/`: bằng chứng log, kết luận và vấn đề chưa xác định.

Không coi mô tả trong tài liệu là bằng chứng code đã thực hiện đúng; đối
chiếu với mã nguồn, test và dữ liệu thực tế khi sửa lỗi.

## Giữ cấu trúc thư mục

| Thư mục | Nội dung |
|---|---|
| `controller/pi/` | Code chạy trên Pi: console, FSM, transport, policy, validation, khóa UART |
| `controller/tests/` | Unit test phần Pi, dùng mock, không điều khiển thiết bị |
| `controller/tools/` | Chẩn đoán Pi, build MAVSDK, phân tích ULog |
| `controller/params/` | Overlay giao tiếp cho UAV thật |
| `simulation/` | Toàn bộ model, công cụ, test, tham số và tài liệu mô phỏng |
| `docs/` | FSM và sơ đồ |
| `logs/YYYY-MM-DD/` | Log gốc, kết quả phân tích và báo cáo theo ngày |

Giữ một README chính ở gốc. Đặt nội dung dài vào tài liệu chuyên biệt và
liên kết từ README. Không tạo thêm thư mục `uav/` lồng trong gốc dự án.
Phần `simulation/` phải có thể chép sang PC khác mà không cần code Pi.

## Các quy tắc điều khiển cần bảo toàn

- Pixhawk/PX4 chạy estimator và mọi vòng điều khiển bay. Pi gửi mục tiêu,
  quản lý FSM và giám sát điều kiện tới đích; không tự thêm PID trên Pi.
- Console hiện dùng local NED: x Bắc, y Đông, z xuống, đơn vị mét. Không
  diễn giải x/y là kinh/vĩ độ hoặc quãng đường tương đối.
- TAKEOFF chụp mốc cất cánh: `z_target = z_launch - height`; giữ x/y đã
  chụp. FLY giữ đích z của chuyến. Không dời đích theo vị trí đang trôi.
- Các lệnh bay là `arm`, `takeoff`, `fly`, `land`, `disarm`. HOLD tự động
  và giữ tới lệnh tiếp theo. Không tự thêm HOLD/RESUME/KILL riêng vào console.
- TAKEOFF/FLY khóa đích đang thực hiện. LAND/DISARM đi qua khóa đích khi
  console xử lý lệnh; không tuyên bố ưu tiên này là bảo đảm thời gian thực.
- Một lệnh `disarm` hiện dùng force-stop cả trên đất và trên không, nội bộ
  gọi `Action.kill()`; có thể làm UAV rơi. Không âm thầm đổi nghĩa lệnh này.
- LAND gửi yêu cầu hạ cánh trước teardown; giữ SDK/plugin trong đường LAND
  bình thường. Không dùng `Offboard.stop()` để thay thế LAND.
- ACK không đồng nghĩa thực hiện xong. Chờ telemetry mới xác nhận mode,
  armed và landed state; LAND/DISARM chỉ trả IDLE khi disarmed và ON_GROUND.
- Dữ liệu cũ, NaN/Inf hoặc mẫu lặp không được hoàn thành dwell. Status có
  thể biểu diễn dữ liệu lỗi bằng null nhưng không sửa cache thành tọa độ 0.
- Không tự ARM, tiếp tục mục tiêu hoặc giành lại Offboard sau mất liên kết/
  đổi mode ngoài ý muốn. Giữ hành vi EXTERNAL/TERMINATION theo FSM.

## Tham số, model và thiết bị

- `hardware` dùng SYS_HITL=0; `hitl` dùng SYS_HITL=1. Không đổi tham số
  trên bo chỉ để vượt kiểm tra profile.
- Hai file `.params` hiện là overlay tối thiểu, không phải cấu hình UAV
  đầy đủ. Bỏ một dòng khỏi overlay không phục hồi giá trị trên Pixhawk.
- Giữ tuning mô phỏng tách khỏi UAV thật. Không thêm giá trị PID/hover/
  failsafe chưa được xác thực chỉ để làm hết cảnh báo hoặc giúp ARM thành công.
- X500 hiện là bản port từ `gz_x500` sang Classic. Tham khảo provenance và
  SETUP; thay plugin/sensor có thể làm khác động lực học dù thông số cơ học
  được giữ. Không gọi bản port là mô hình đã xác thực của UAV thật.
- Không sửa tay dữ liệu nguồn gốc để tạo cảm giác đã kiểm chứng: giữ
  revision/hash lịch sử, ghi riêng kết quả đối chiếu mới và giới hạn của nó.
- Review, unit test và kiểm tra tĩnh không được tự mở phiên điều khiển
  hoặc phát lệnh motor. Thử trên thiết bị thực hiện theo phạm vi đã được
  người vận hành cho phép; thử motor trên bàn cần tháo cánh.
- Không suy ra lỗi GPS chỉ từ x/y/z khác 0. Không kết luận nguyên nhân Pi
  tắt hoặc motor quay khi reboot nếu thiếu dữ liệu của chính sự kiện đó.

## Kiểm tra sau thay đổi

Chạy từ gốc repository, chọn kiểm tra phù hợp phần đã sửa:

```bash
python3 -B -m unittest discover -s controller/tests -p 'test_*.py'
python3 -B -m unittest discover -s simulation/tests -p 'test_*.py'
python3 simulation/x500/check_setup.py --static
bash -n controller/tools/build_mavsdk_pi.sh simulation/x500/stop_gazebo.sh
```

Khi sửa FSM/transport, thêm hồi quy cho lỗi thực tế và xác nhận không tự
ARM, không làm mất quyền LAND/DISARM, không nhận nhầm ACK/dữ liệu cũ.
Khi sửa mô phỏng, kiểm tra tài nguyên, motor mapping, world và khả năng
chạy test khi chỉ chép riêng `simulation/`. Smoke test HITL là bài tích
hợp riêng, không ghép vào unittest mặc định.

Sửa tài liệu thuần túy cần kiểm tra liên kết, đường dẫn và cú pháp lệnh;
không cần chạy lại toàn bộ unit test nếu code không thay đổi. Đồng bộ FSM,
sequence/draw.io và hướng dẫn khi thay đổi hành vi. Không ghi số test cố
định mà không kiểm tra lại nếu vừa thêm hoặc xóa test.

## Log và báo cáo kết quả

Giữ nguyên ULog gốc. Dùng `controller/tools/analyze_logs.py` để tái lập
số liệu; không sửa `analysis.json` thủ công để khớp kết luận. Phân biệt
sai số theo estimator với vị trí vật lý, và đoạn Offboard với đoạn RTL.

Ghi rõ việc đã sửa, kiểm tra đã chạy, kết quả và phần chưa xác thực.
Phân biệt unit test/mock, kiểm tra model tĩnh, chạy Gazebo/HITL và bay thật.
Không khẳng định lỗi phần cứng đã hết dựa trên test phần mềm.

Không đưa venv, cache, session log, token hoặc ULog lên Git ngoài ý muốn.
Repository công khai `DA1-UAV` có chủ ý lưu bốn ULog tại `logs/2026-10-24/` để tái
lập phân tích trên máy khác; giữ nguyên các file đó và mặc định bỏ qua
ULog phát sinh ở thư mục khác.
Giữ license của model và cập nhật README khi thêm file cần theo dõi.
