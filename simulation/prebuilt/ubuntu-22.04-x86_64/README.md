# Plugin Classic dùng sẵn

Bộ này chứa 8 plugin được model X500 sử dụng và 4 thư viện protobuf hỗ trợ.
Chỉ dành cho **Ubuntu 22.04 x86_64, Gazebo Classic 11**; không dùng trên Pi
ARM64, Windows hoặc Gazebo mới. Người dùng không cần tải/build PX4 trên PC
để chạy model HITL đã có trong Git. Firmware PX4 vẫn chạy trên Pixhawk thật.

Từ gốc dự án, chạy `bash simulation/install_classic.sh` để cài Gazebo và
Python dependency. Launcher tự chọn thư viện ở `lib/`. Có thể kiểm tra riêng
bằng `python3 simulation/x500/prebuilt.py`; công cụ này không mở USB hoặc
khởi chạy mô phỏng.
Kết quả thực tế và giới hạn nằm trong [VALIDATION.md](VALIDATION.md).

Các file được lấy từ build PX4 v1.16.0/Classic trên máy dự án. Bản sao đã
đổi RUNPATH sang `$ORIGIN` bằng CMake và bỏ symbol/debug không cần thiết bằng
`strip --strip-unneeded`; không sửa hay build lại file nguồn. `manifest.json`
lưu target, SHA-256 trước/sau đóng gói và revision/trạng thái checkout tại
thời điểm đóng gói. Đây không phải chứng cứ rằng build gốc được tạo từ
checkout sạch; ngày/đầy đủ môi trường build ban đầu không được ghi lại.

Copyright và license được giữ trong `licenses/`. Thư viện hệ thống do apt
cài riêng, không được sao chép vào bộ này. Model/world/mesh của dự án có
license riêng ở `simulation/x500/generated/models/`.

Để thay bộ binary, người bảo trì build/kiểm thử phiên bản mới trên đúng
môi trường trước, rồi dùng `simulation/tools/package_classic.py --px4 PATH`.
Công cụ đóng gói từ chối ghi đè bộ đã có. Review manifest, chạy kiểm tra
dependency và test trên bản `simulation/` chép sang vị trí khác trước khi
phát hành. Không suy ra tương thích HIL/firmware hoặc kết quả bay chỉ từ
việc có file `.so`, loader check hay xác thực SDF.
