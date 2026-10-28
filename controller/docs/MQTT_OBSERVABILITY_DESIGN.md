# Thiết kế MQTT, log và giám sát Pi/Pixhawk (đề xuất)

Tài liệu này cụ thể hóa bản nháp ngày 28/10/2026. Đây là **thiết kế**, chưa phải
chức năng đã triển khai. Hiện Pi điều khiển Pixhawk qua `pi/console.py` và
`GpsMissionControl`; web chưa gửi lệnh vào phiên này. Không thử publish lệnh bay
trên broker thật khi chưa có adapter và quy trình kiểm thử HITL.

## 1. Ranh giới trách nhiệm

```text
Web/backend ── MQTT broker ── control service (Pi)
                                     │ IPC: lệnh + ACK + trạng thái
                                     ▼
                              flight service (Pi) ── MAVSDK ── Pixhawk
                                     │
                              log sự kiện/telemetry (Pi)
```

- **Control service** giữ kết nối MQTT, xác thực và kiểm tra bản tin, quản lý
  cấu hình cho phép thay đổi, gửi trạng thái/nhật ký lên broker. Nó không gọi
  MAVSDK, không sở hữu cổng MAVLink và không tự quyết định UAV đã tới đích.
- **Flight service** là chủ duy nhất của phiên MAVSDK/Pixhawk. Nó chạy FSM hiện
  có, kiểm tra preflight, lệnh, mode và telemetry, rồi trả kết quả qua IPC.
  Tách process giúp MQTT mất kết nối không trực tiếp đóng phiên bay, nhưng
  không thay thế failsafe của PX4.
- IPC có một hàng lệnh có thứ tự, giới hạn dung lượng và `command_id`. LAND /
  DISARM được ưu tiên tại chỗ nhận lệnh, song một RPC MAVSDK đang chờ vẫn có
  thể làm trễ xử lý. Không quảng cáo đây là kênh dừng khẩn cấp thời gian thực.
- QGC vẫn nhận MAVLink qua router; QGC **không** subscribe MQTT trực tiếp.
  PX4 ULog trên SD, log Pi và thông báo QGC là ba nguồn chứng cứ riêng.

## 2. Topic và bản tin đề xuất

Giao thức backend hiện mới ghi `lac/<deviceID>/control`, `/data`, `/debug` và
sáu lệnh `c:...;`; chưa có lệnh triển khai, Pause, Resume, Cancel, LAND,
return-home hay ACK. Các topic dưới đây là **đề xuất phiên bản mới**; chỉ đổi
khi backend thống nhất định dạng. Không trộn lệnh thử v2 vào topic legacy.

| Topic đề xuất | Chiều | Nội dung | Retain |
|---|---|---|---|
| `lac/<id>/v2/command` | backend → Pi | Một lệnh JSON đầy đủ, có `command_id`, `mission_id`, hạn dùng | Không |
| `lac/<id>/v2/ack` | Pi → backend | `received`/`rejected`/`accepted`, lý do và thời gian | Không |
| `lac/<id>/v2/state` | Pi → backend | Phase Pi, mode/armed/landed PX4, đích, tuổi telemetry | Có thể giữ trạng thái cuối nhưng phải kèm `observed_at` và `online` |
| `lac/<id>/v2/health` | Pi → backend | Pi, Pixhawk, link, nguồn, dung lượng log | Có thể; phải kèm tuổi mẫu |
| `lac/<id>/v2/event` | Pi → backend | INFO/WARNING/ERROR/CRITICAL theo từng sự kiện | Không |
| `lac/<id>/v2/availability` | Pi → backend | Online/offline và `boot_id` | Có; dùng Last Will |

Đề xuất QoS 1 cho command/ACK/event quan trọng, QoS 0 cho telemetry chu kỳ;
QoS chỉ xác nhận vận chuyển qua broker, nên `command_id` vẫn bắt buộc để
chống thực thi lặp. Không dùng retain hoặc phiên subscribe bền cho lệnh bay.

Mỗi lệnh nên là **một bản tin nguyên tử**, không gửi lat/lon/height/speed rời
rạc rồi tự khởi hành khi nhận trường cuối. Ví dụ bản tin triển khai:

```json
{
  "schema": 2,
  "command_id": "opaque-unique-id",
  "mission_id": "opaque-mission-id",
  "issued_at_utc": "2026-10-28T10:00:00Z",
  "expires_at_utc": "2026-10-28T10:00:10Z",
  "type": "gps_start",
  "params": {
    "a": {"lat_deg": 21.028511, "lon_deg": 105.854444},
    "b": {"lat_deg": 21.02855, "lon_deg": 105.85448},
    "height_above_launch_m": 2.5,
    "speed_m_s": 0.4
  }
}
```

Control service từ chối schema sai, ID trùng, bản tin hết hạn, `retain=true`,
giá trị không hữu hạn, lệnh ngoài allowlist hoặc thiếu quyền. Nó trả ACK
**nhận lệnh** riêng với sự kiện **PX4 xác nhận mode** và **đã tới đích**; ACK
MQTT không có nghĩa UAV đã bay. Sau Pi reboot, lệnh cũ không được chạy lại.
`pause`, `resume`, `cancel`, `land`, `disarm`, `return_home`, `return_height`
đều phải đi qua FSM hiện có. Cấu hình phần cứng/camera và OTA dùng nhóm lệnh
riêng, không diễn giải như lệnh bay.

## 3. Log tại Pi và bản tin debug

Giữ **log gốc trên Pi** trong kho lưu trữ có giới hạn dung lượng. Dùng **một
file JSON Lines (`.jsonl`) cho mỗi phiên bay**: mỗi dòng là một sự kiện hoặc
mẫu sức khỏe, có `record_type` và cùng bộ trường thời gian/phiên. Như vậy
có thể mở trực tiếp và xuất CSV thành bảng với các cột CPU, RAM, nhiệt độ,
phase, mức cảnh báo; trường chưa có dữ liệu để `null`. Không ép cả phiên vào
một dòng văn bản dài. Tạo file mới theo phiên, xoay vòng nếu quá kích thước,
giữ mức dung lượng tối đa và cảnh báo khi đĩa gần đầy. Ghi tuần tự; không để
MQTT chậm chặn vòng điều khiển bay. Với sự kiện quan trọng, flush sớm.

| Trường trong mỗi sự kiện | Ý nghĩa |
|---|---|
| `ts_utc`, `monotonic_ms`, `boot_id`, `flight_id` | Thời gian và phiên để đối chiếu sau reboot/lệch đồng hồ |
| `source`, `severity`, `event`, `message` | Pi/MQTT/PX4/camera; INFO/WARNING/ERROR/CRITICAL; mã sự kiện; mô tả |
| `command_id`, `mission_id`, `phase_before`, `phase_after` | Truy vết lệnh và FSM |
| `px4_mode`, `armed`, `landed_state`, `telemetry_age_ms` | Bằng chứng trạng thái PX4 tại thời điểm đó |
| `details` | Trường có cấu trúc: lý do từ chối, ACK, exception đã lược bỏ bí mật |

Ghi sự kiện cho: khởi động/tắt service, kết nối/ngắt MQTT/MAVLink, nhận và
từ chối lệnh, mọi chuyển phase, ARM/TAKEOFF/FLY/Mission/HOLD/LAND/DISARM,
timeout, failsafe, lỗi sensor/nguồn, cập nhật cấu hình, OTA. Ghi **nhật ký
bước** (requested → accepted → mode confirmed → target confirmed) để biết
chu trình đã đi qua bước nào. Lấy snapshot telemetry định kỳ ở tần suất
thấp vào cùng file phiên; không ghi mọi gói MAVLink thô vào JSONL. ULog PX4 là
nguồn chi tiết cho phân tích điều khiển bay.

Log level có thể thay đổi **theo module** qua lệnh cấu hình hợp lệ
(`mqtt`, `flight`, `pixhawk`, `camera` khi có): INFO/DEBUG với thời hạn tự
hết để tránh đầy đĩa. Không cho tắt ERROR/CRITICAL, các bước ARM/LAND/
DISARM, ACK hay chuyển phase. Lệnh bật DEBUG phải được ghi vào log, giới
hạn tốc độ và không ghi secret/payload chứa mật khẩu. Nếu lưu trên microSD,
giới hạn tần suất ghi và dung lượng; khi có SSD/ổ lưu trữ riêng, đặt
`--log-dir` vào đó sau khi kiểm tra quyền ghi và đường dẫn.

`/event` chỉ gửi sự kiện đã chọn, có giới hạn tốc độ; `/debug` legacy chỉ
được dùng sau khi backend chốt tương thích. MQTT ngắt thì log vẫn lưu local;
outbox gửi lại chỉ áp dụng cho sự kiện/ACK đã có ID, có giới hạn dung lượng.
Không phát lại lệnh điều khiển cũ. MQTT Explorer dùng để **xem** topic,
không thay thế kho log hay phân tích ULog.

Thông báo PX4 xuất hiện trong QGC có thể thu qua MAVSDK `StatusText` để lưu
vào log Pi và chuyển lên MQTT. Cảnh báo do Pi tự tạo sẽ hiện trong web/MQTT;
đưa chúng vào ô Vehicle Messages của QGC cần một bridge MAVLink STATUSTEXT
riêng, hiện chưa có. Không ghi rằng QGC đã nhận cảnh báo Pi khi bridge đó
chưa được triển khai và kiểm thử.

## 4. Trường sức khỏe cần thu thập

| Nguồn | Trường nên có | Tình trạng code hiện tại |
|---|---|---|
| Pi host | CPU %, nhiệt độ °C, RAM used/available, swap, disk free/used, uptime, `boot_id`, throttling/undervoltage, Wi-Fi RSSI/link | `diagnose_pi.py` đọc nhiệt độ, boot/throttling và journal theo yêu cầu; chưa thu liên tục CPU/RAM/disk/link |
| Flight service | process alive, RSS, CPU %, lỗi cuối, phase, hàng lệnh, tuổi lần poll/telemetry | `status()` có phase và lỗi; chưa có process metrics/queue |
| MQTT service | connected, broker RTT/last RX/TX, reconnect count, outbox size, last ACK | Chưa có service |
| Pixhawk | connected, mode, armed, landed, health, GPS fix/accuracy, local/global position và tuổi mẫu, battery, failsafe/status text | Có phần mode/armed/landed/health/local/global; pin, GPS info, status text chưa được đăng ký đầy đủ |
| Camera (nếu lắp) | detected, recording/streaming, resolution, fps, bitrate, frame drop, storage | Chưa có module camera; chỉ khai báo trường khi có thiết bị |

Mỗi giá trị cần đơn vị, `observed_at_utc`, `age_ms` và trạng thái
`valid`/`unavailable`; không tự thay dữ liệu thiếu bằng 0. WARNING là dấu hiệu
cần kiểm tra (ví dụ nhiệt độ hoặc dung lượng giảm); CRITICAL là trạng thái
đang ảnh hưởng đến điều khiển/ghi log. Ngưỡng cảnh báo chỉ đặt sau khi đo
thực tế trên đúng Pi, nguồn và camera, không đoán một ngưỡng chung.

## 5. Cấu hình từ xa và OTA

- Chia cấu hình thành: **đọc được** (ngưỡng, tốc độ gửi telemetry), **có thể
  thay đổi khi disarmed/on ground** (camera, một số giới hạn ứng dụng), và
  **không sửa qua MQTT** (tham số PX4, motor mapping, calibration, secret,
  nguồn/failsafe). Mỗi thay đổi cần version, kiểm tra khoảng giá trị, ACK,
  log trước/sau và đường quay về cấu hình trước.
- File cấu hình chứa broker host/port, TLS CA và device ID; secret lấy từ
  file quyền hạn hạn chế hoặc secret store. Không gửi credential qua MQTT,
  không commit Git. Cổng `8883` trong bảng chỉ là thông tin chưa xác minh;
  không tắt xác minh chứng chỉ để kết nối cho nhanh.
- OTA **không phải lệnh bay**. Tách gói phần mềm Pi khỏi firmware Pixhawk.
  Trước OTA phải có `armed=false`, `ON_GROUND`, nguồn và dung lượng đủ, gói
  có hash/chữ ký, version/thiết bị phù hợp, staging và rollback. Không OTA
  trong chuyến bay. URL/IP download là một trường cấu hình có kiểm tra nguồn,
  không phải lệnh shell chạy trực tiếp từ MQTT. Việc flash firmware Pixhawk
  cần quy trình riêng và kiểm thử trên bàn; chưa triển khai trong dự án này.

## 6. Thứ tự triển khai

1. Chốt broker, TLS, `deviceID`, quyền publish/subscribe và schema/ACK với
   backend; thử chỉ đọc bằng MQTT Explorer. Bản giao thức sáu lệnh cũ chưa
   đủ để tự chạy nhiệm vụ.
2. Thêm event log JSONL và metrics Pi/Pixhawk, có rotation, kiểm tra Pi
   reboot/mất mạng/đĩa đầy. So sánh với log console và ULog.
3. Tách flight service một chủ MAVSDK và control service MQTT; thử các lệnh
   bằng fake controller/HITL trước khi cho quyền actuation trên UAV thật.
4. Chỉ sau khi đường bay và log ổn định mới bổ sung cấu hình camera/OTA.

Nguồn tham khảo: [MQTT QoS/Retain/Will](https://mosquitto.org/man/mqtt-7.html),
[MAVSDK Telemetry](https://mavsdk.mavlink.io/main/en/cpp/api_reference/classmavsdk_1_1_telemetry.html).
