# Hiển thị terminal và nhật ký bay

Thông báo trong chương trình dùng tiếng Anh ngắn gọn. Tài liệu giải thích
bằng tiếng Việt; tên trường, lệnh, tham số và ví dụ đầu ra giữ nguyên như
trong code. Lệnh bay từ web đi qua MQTT; phần điều khiển log/debug qua
MQTT chưa được triển khai.

## Status và terminal

`status` trong `flight/client.py` và `console.py` hiển thị NED, GPS
POSITION, độ cao theo launch/Home/MSL, vận tốc NED, trạng thái Pi/mode
PX4, sức khỏe, pin và mục tiêu nhiệm vụ. Status IPC của Flight Service
còn chứa thông số sức khỏe Pi. Console trực tiếp không có dữ liệu sức
khỏe máy từ service, nên các trường tương ứng hiện N/A.

Tuổi dữ liệu được giữ để nhận biết mẫu cũ; một giá trị còn xuất hiện
không có nghĩa nó vừa được cập nhật. `status --json` xuất chẩn đoán đầy
đủ; `console.py --check` giữ đầu ra JSON cho công cụ kiểm tra.

Flight Service in thời gian, ID lệnh, thay đổi trạng thái, tải nhiệm vụ
và báo cáo waypoint từ PX4. Snapshot định kỳ và thông báo SDK mức DEBUG
được lưu vào file để terminal dễ theo dõi. File JSONL lưu giờ UTC;
terminal hiển thị theo Asia/Bangkok. Thông báo gốc SDK/PX4 được giữ
nguyên nội dung và mã sự kiện chỉ nguồn.

Ví dụ chuỗi sự kiện (thời gian và số liệu chỉ minh họa):

```text
INFO FLIGHT COMMAND_REQUESTED | gps_start requested
INFO FLIGHT MISSION_VALIDATED | GPS plan validated
INFO FLIGHT FLIGHT_STATE_CHANGED | Climb started; waiting for target and HOLD
INFO FLIGHT TAKEOFF_COMPLETE | Takeoff complete
INFO FLIGHT MISSION_UPLOADED | Uploaded 6 waypoints
INFO FLIGHT FLIGHT_STATE_CHANGED | PX4 MISSION confirmed
INFO FLIGHT WAYPOINT_TARGET_CHANGED | Target A (1/6)
INFO FLIGHT WAYPOINT_REACHED | PX4 reported waypoint A reached
INFO FLIGHT WAYPOINT_TARGET_CHANGED | Target B (2/6)
INFO FLIGHT FLIGHT_STATE_CHANGED | Mission complete; final position, height and HOLD confirmed
```

ACK/chấp nhận lệnh và hoàn tất thao tác là các sự kiện khác nhau.
Tiến độ MissionRaw chỉ ra mục tiêu hiện tại; MISSION_ITEM_REACHED là
báo cáo PX4 đã đạt một mục nhiệm vụ. Mục 0 là lệnh tốc độ; mục 1..N
ứng với waypoint. Nhãn A..Z rồi WP27..WP50 theo nhiệm vụ app đã tải;
HOME được dùng cho nhiệm vụ quay về.

Báo cáo sai nguồn, ngoài phạm vi, trùng lặp và callback từ subscription
cũ bị bỏ qua. Subscription được hủy khi cancel/thay nhiệm vụ/LAND/DISARM.
Các báo cáo chỉ phục vụ hiển thị, không điều khiển FSM. Bản tin reached
của MAVLink không chứa ID nhiệm vụ, nên không thể nhận diện chắc chắn
mọi bản tin cũ bị trễ trên đường truyền. Hoàn tất cuối cùng vẫn yêu cầu
vị trí/độ cao mới và HOLD được xác nhận.

## Lưu trữ

Service lưu vào `--log-dir`, mặc định `session-logs/services`. Client
kỹ thuật ghi `client-*.jsonl` vào `session-logs/services` tính từ thư mục
làm việc; nên chạy tại `~/uav-gps`. Console ghi `console-*.jsonl` cùng
file chẩn đoán/lỗi Python vào `--log-dir`, mặc định `session-logs`.
File fault dùng chẩn đoán lỗi Python; tiến trình bay thông thường nằm
trong JSONL.

Bản ghi chứa lệnh/tham số, đầu vào/phản hồi client, lệnh được nhận hoặc
từ chối, chuyển trạng thái, last_error, ACK/cờ xác nhận, waypoint, nội
dung SDK/PX4, snapshot và CPU/RAM/swap/disk/nhiệt độ/thời gian hoạt động.
Snapshot được lấy tối đa 2 Hz; thông số máy mỗi 5 giây khi vòng lặp xử lý
được. RPC native đang chờ có thể làm chậm lấy mẫu; log không ghi mọi mẫu
cảm biến. ULog Pixhawk vẫn cần cho phân tích estimator/motor.

Callback MAVSDK đưa sự kiện PX4 vào hàng đợi có giới hạn; số sự kiện bị
bỏ khi đầy được ghi lại. Mẫu CPU đầu tiên có thể chưa có. RAM hiện tại
của process và RAM đỉnh được ghi riêng; thông số không đọc được giữ null.

Mỗi file JSONL được xoay ở khoảng 20 MiB và không tự xóa file cũ. Cần
bảo đảm dung lượng trống. Mất nguồn đột ngột vẫn có thể mất dữ liệu mới
nhất dù chương trình đã flush và gọi fsync ở các sự kiện được chọn.

Để gộp theo thời gian thành một CSV, chạy tại thư mục controller:

```bash
.venv/bin/python pi/observability/export_logs.py \
  --log-dir session-logs/services --output flight-review.csv --format csv
```

Lệnh đọc JSONL control/flight/client/console trong thư mục đã chọn và
tạo CSV mới, không ghi đè file xuất đã có. Dùng cùng thư mục log nếu muốn
bản xuất bao gồm cả console và service. CSV chứa các cột được chọn;
JSONL giữ dữ liệu lồng đầy đủ. Dùng `--format jsonl` để xuất theo thời
gian và giữ mọi trường.

## Pin

Pi chỉ giám sát số đo/ước lượng và ngưỡng đọc từ PX4. PX4 thực hiện LAND
theo cấu hình pin; bộ giám sát trên Pi không tự gửi LAND hoặc dừng motor.
Cần đọc lại cấu hình đang chạy trên bo. Hai overlay hiện chọn cảnh báo
30%/15% và PX4 LAND ở 7%; xem
[setup và pin](HARDWARE_SETUP.md#giám-sát-pin-và-chính-sách-hạ-cánh).

## Giới hạn kiểm chứng

Unit test dùng mock để kiểm tra định dạng, ghi file, lọc nguồn/chỉ số,
subscription cũ, báo cáo trùng, dữ liệu pin cũ và việc lỗi dọn observer
không chặn LAND. Cách hiển thị/log và subscription mới vẫn cần kiểm
chứng trực tiếp trên Pi/HITL.

## LAST_ERROR

LAST_ERROR là lỗi gần nhất bộ điều khiển ghi trong phiên, không phải
danh sách mọi lệnh bị từ chối. Nó có thể còn giữ sau sự kiện. Xem phase,
mode, tuổi telemetry và log có thời gian để xác định lỗi còn hiện tại
hay không. Lỗi cú pháp/kiểm tra lệnh cục bộ cũng xuất hiện trong log
client/lệnh. N/A nghĩa là chưa có giá trị được ghi, không phải bằng
chứng toàn bộ UAV đều khỏe.

## Ví dụ status

Dữ liệu minh họa được tạo bằng bộ định dạng hiện tại, không phải số đo bay thật:

```text
SYSTEM     profile=hitl  connected=true  actuation=true
FLIGHT     phase=GPS_RUNNING  mode=MISSION  armed=true  landed=IN_AIR
NED (m)    north=5.12  east=-1.35  down=2.21  age=0.12s
POSITION   lat=21.0051900  lon=105.8441680  msl_m=103.02  home_m=-1.20  age=0.12s
HEIGHT     launch_m=3.02  target_m=3.00
VEL (m/s)  north_m_s=0.94  east_m_s=0.00  down_m_s=0.00  age=0.12s
HEALTH     all_ok=true  invalid=[]  age=0.12s
BATTERY    percent=65.00  voltage_v=23.80  current_a=12.10  warning=NORMAL  age=0.12s
MISSION    phase=GPS_RUNNING  points=6  target=B  speed_m_s=1.00
CONTROL    takeoff_complete=true  can_send_target=false  locked=true
PI HEALTH  cpu_pct=12.50  temp_c=47.20  ram_used_mib=650.00  ram_available_mib=7100.00  disk_available_mib=38000.00
BAT LIMITS BAT_LOW_THR=0.30  BAT_CRIT_THR=0.07  BAT_EMERGEN_THR=0.05  COM_LOW_BAT_ACT=2
LAST_ERROR N/A
```

## Độ cao hiển thị trên web

### Nguyên nhân và các mốc đo

Trong bản `telemetry_reader.py` được cung cấp ngày 14/11, gateway lấy
`GLOBAL_POSITION_INT.relative_alt / 1000` vào `altitude_relative`.
Trường MAVLink này là độ cao so với Home hiện tại của PX4, không bảo đảm
trùng mốc TAKEOFF của Flight Service. Khi độ cao Home thay đổi, giá trị
có thể âm dù UAV đang ở trên điểm cất cánh.
[Định nghĩa MAVLink](https://mavlink.io/en/messages/common.html#GLOBAL_POSITION_INT).
Ví dụ ULog của dự án ở [FLIGHT_LOG_2026-11-10.md](../../logs/2026-11-10/REPORT.md).

| Trường | Mốc/nguồn | Hiển thị |
|---|---|---|
| `height_above_launch_m` | `launch_ned.down_m - local_ned.down_m` của Flight Service | Độ cao ước lượng so với điểm cất cánh |
| `altitude_relative` | PX4 `GLOBAL_POSITION_INT.relative_alt` | Độ cao so với Home PX4 |
| `altitude_msl` | PX4 `GLOBAL_POSITION_INT.alt` | Độ cao tuyệt đối MSL |
| `altitude_agl` | Dữ liệu khoảng cách mặt đất hợp lệ, gateway hiện lấy `ALTITUDE.bottom_clearance` | Khoảng cách tới mặt đất bên dưới |

Không lấy trị tuyệt đối, kẹp âm về 0, trừ mẫu relative đầu tiên hay thay
giá trị đo bằng độ cao nhiệm vụ. Các cách đó che sai số/mốc thay đổi.
Độ cao theo local NED vẫn là ước lượng và có thể trôi; chưa phải phép đo
độc lập tới mặt đất. Muốn đo trực tiếp AGL cần cảm biến khoảng cách hợp
lệ trong tầm đo. Không có nguồn hợp lệ thì hiển thị chưa có dữ liệu.

### Phần đã chuẩn bị trong repo

[`observability/web_altitude.py`](../pi/observability/web_altitude.py) có
`FlightAltitudeReader`. Nó chỉ yêu cầu `status` qua Unix socket, không
mở MAVLink, không gửi lệnh bay và không sửa tham số. Mỗi lần đọc trả:

```json
{"height_above_launch_m": 2.0, "height_above_launch_valid": true, "height_above_launch_source": "flight_service_local_ned"}
```

Số 2.0 là ví dụ số đo. Giá trị chỉ hợp lệ khi connected, có mốc launch,
local NED mới không quá 1 giây, và độ cao khớp với mốc/vị trí trong cùng
status. Thiếu mốc trước TAKEOFF, service mất kết nối hoặc IPC timeout thì
trả null/false; không tái sử dụng độ cao của lần đọc trước. Thời gian chờ
IPC mặc định 0,2 giây, để không giữ luồng telemetry lâu khi Flight Service bận.

### Tích hợp vào gateway trên Pi

Bộ gateway thực tế ở `~/uav_gateway_code` là dự án riêng. Chưa có
`mqtt_publisher.py`, `lac_protocol.py`, `fields.json` hay backend trong repo
này, nên helper chưa được nối vào bản tin gửi lên web. Các bước tích hợp:

1. Đồng bộ `controller/` vào `~/uav-gps` và chạy Flight Service như hiện tại.
2. Trong `telemetry_reader.py`, sau các import hiện có (`sys` và `Path` đã có), thêm:

   ```python
   sys.path.insert(0, str(Path.home() / 'uav-gps' / 'pi'))
   from observability.web_altitude import FlightAltitudeReader
   ```

   Dòng đầu cho Python tìm module trong code controller đã đồng bộ. Dòng
   thứ hai nhập lớp chỉ đọc độ cao; không tạo kết nối MAVLink.

3. Trong `main()`, trước vòng lặp đọc telemetry, tạo một đối tượng:

   ```python
   flight_altitude = FlightAltitudeReader('/tmp/uav-flight.sock')
   ```

   Dòng này chọn socket cùng Flight Service; nếu chạy systemd dùng
   `/run/uav/flight.sock` thay thế.

4. Ngay sau dòng `values = reader.snapshot(now, args.uav_id, sequence)`, thêm:

   ```python
   values.update(flight_altitude.snapshot())
   ```

   Dòng này thêm ba trường ở trên vào snapshot trước khi ghi JSON/publish.
   Giữ nguyên `altitude_relative` để đối chiếu Home PX4.

5. Trong `fields.json`/`lac_protocol.py` và bộ đóng gói MQTT, khai báo
   trường mới theo định dạng gateway/backend đang dùng. Nếu giao thức dùng
   chỉ số trường, phải thống nhất chỉ số mới ở cả hai đầu; không tự đổi nghĩa
   chỉ số 28 (`altitude_relative`) và không chỉ thêm key rồi cho rằng nó đã
   được truyền. Kiểm tra payload MQTT thật có các trường mới.
6. Backend lưu các trường mới trong telemetry và lịch sử. Web dùng
   `height_above_launch_m` với `height_above_launch_valid=true` cho bảng,
   số giám sát và đồ thị; dùng nhãn “Độ cao so với điểm cất cánh”. Nếu
   thiếu/null/không hợp lệ, hiện “—”; giữ khoảng trống trên đồ thị thay vì
   vẽ 0 hoặc kéo dài mẫu cũ. Giá trị 0 thực sự vẫn là số đo hợp lệ.

`altitude_agl` dùng nhãn riêng “Độ cao so với mặt đất” khi có dữ liệu hợp
lệ; không fallback sang height trên launch rồi gán nhãn AGL.

### Xác minh sau tích hợp

- Đối chiếu Flight Service `status.height_above_launch_m`, JSON gateway,
  payload MQTT, backend và web tại cùng thời điểm.
- Home PX4 thay đổi không được làm web đổi sang `altitude_relative`.
- Thiếu service/mốc/dữ liệu mới phải hiện chưa có dữ liệu.
- Khi hạ cánh, tiếp tục hiển thị số đo; không tự ép về 0.
- Lịch sử cũ chỉ lưu relative altitude không đủ để khôi phục launch height;
  cần ULog/raw telemetry và mốc cất cánh của chuyến tương ứng.

Unit test đã kiểm tra Home đổi dấu, dữ liệu cũ/NaN, thiếu launch và IPC
timeout bằng mock. Chưa xác minh đầu cuối trên gateway/Pi/web thực tế.
