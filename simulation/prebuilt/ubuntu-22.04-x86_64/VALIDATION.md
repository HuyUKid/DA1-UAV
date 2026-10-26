# Kết quả kiểm tra gói plugin — 26/10/2026

Môi trường kiểm tra: Ubuntu 22.04.5 x86_64, Gazebo Classic/libgazebo11
11.10.2+dfsg-1, Python 3.10. Chưa thử cài apt trên máy sạch.

- 30 unittest mô phỏng đạt, gồm kiểm tra đủ plugin cho model, checksum,
  thiếu/hỏng thư viện, chọn bundle mặc định và từ chối host không tương thích.
- Đã chép riêng `simulation/` sang thư mục tạm mới; bỏ biến môi trường
  `GAZEBO_*` và `LD_LIBRARY_PATH` kế thừa trước khi thử.
- `install_classic.sh --skip-system` tạo venv mới và cài pymavlink/lxml/
  fastcrc bằng wheel thành công; không clone/build PX4 hoặc chạy compiler.
- Checksum, target và `ldd` đạt; thư viện hỗ trợ được resolve trong bundle
  đã di chuyển, không phải cây PX4 build ở Home.
- Cả 12 thư viện load được bằng `ctypes.CDLL` ở vị trí mới.
- `check_setup.py` đạt và `launch.py --serial /dev/null --validate` xác thực
  SDF model/world đạt. `/dev/null` chỉ là giá trị model tạm, không được mở.
- RUNPATH của các bản sao đã chuyển sang `$ORIGIN`; file build gốc giữ nguyên.

Ở lần kiểm tra artifact ban đầu chưa khởi chạy world/USB/HIL. Loader/SDF/test đạt không chứng minh động lực học,
firmware/bo Pixhawk hay khả năng bay tương thích. Host kiểm tra đã có runtime;
khả năng cài apt từ đầu và các phiên bản package khác vẫn cần kiểm chứng.

## Kiểm tra HIL DISARM tiếp theo, cùng ngày

Đã bổ sung `pyserial` vào dependency và tạo venv trên PC thật. Smoke test
40 giây với PX4 FMUv6C firmware 1.17.0 đạt: có heartbeat/actuator/local
position mới, không ghi nhận ARM, ON_GROUND, tốc độ ước lượng
0,0054385 m/s và đọc được pose model. Report local:
`simulation/artifacts/connection-1793000125063132598.json`.

Đã mở Gazebo GUI và kiểm tra console chỉ đọc trên PC qua UDP 14540:
IDLE, SYS_HITL=1, ON_GROUND, armed=false, health_all_ok=true và không
termination. Chưa kiểm chứng TAKEOFF/HOLD/FLY/LAND hoặc tuning bay.
