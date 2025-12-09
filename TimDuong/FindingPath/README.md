# FindingPath

Dự án trình diễn cách so sánh các thuật toán tìm đường phổ biến (BFS, DFS, Dijkstra, UCS, Greedy Best-First, A*) trên một khu vực thực tế lấy dữ liệu từ OpenStreetMap.  Ứng dụng
được viết bằng Python và sử dụng `osmnx` để tải bản đồ, `networkx` để vận hành
trên đồ thị.  Phần giao diện web sử dụng Leaflet và tile OpenStreetMap để hiển
thị khu vực tương tác trực tiếp trong trình duyệt.

## Tính năng chính

- Tải một khu vực nhỏ từ OpenStreetMap (theo tên địa điểm hoặc tọa độ trung
  tâm) và hiển thị trực tiếp trên giao diện web.
- Biến đổi dữ liệu đường sá thành đồ thị, cho phép chặn các tuyến đường (tắc
  hoặc ngập) theo tên đường hoặc đa giác ngập.
- So sánh các thuật toán tìm đường cơ bản (BFS, DFS, Dijkstra, UCS, Greedy Best-First, A*) và trả về
  đường đi cùng tổng chiều dài và tổng chi phí sau khi áp hệ số phạt.
- Trực quan hóa đường đi ngay trên trình duyệt bằng Leaflet và có thể điều
  chỉnh điểm xuất phát/đích bằng thao tác click chuột.
- Hiển thị đồ thị (nút/cạnh) trực tiếp trên bản đồ, có thể ẩn nền gạch để chỉ
  quan sát Graph đơn thuần. Các cạnh giữ nguyên hướng lưu thông để dễ phân
  tích đường một chiều.
- Xuất bản đồ tương tác dạng HTML từ CLI để lưu trữ hoặc chia sẻ.
- Xuất đồ thị ở định dạng GraphML kèm thông tin cạnh bị chặn và hệ số phạt để
  phân tích hoặc chạy thuật toán bằng công cụ khác.

## Yêu cầu hệ thống

- Python 3.9 trở lên
- Các thư viện trong `requirements.txt` (bao gồm `osmnx>=2.0.6`)
- Kết nối Internet để `osmnx` tải dữ liệu OpenStreetMap lần đầu tiên
- Kết nối Internet khi chạy web để nạp Leaflet CDN và tile bản đồ

Cài đặt phụ thuộc:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy giao diện web (Python + Flask)

Giao diện web cho phép chọn địa điểm, đặt điểm xuất phát/đích trực tiếp trên
map, chọn thuật toán và xem kết quả ngay lập tức.

```bash
flask --app app run --debug
```

Sau đó truy cập http://127.0.0.1:5000/ để sử dụng. Một số tính năng nổi bật:

- Tải khu vực bằng tên địa điểm, hiển thị đồ thị đường sá (màu xám) và có thể
  phóng to/thu nhỏ.
- Click vào bản đồ để đặt (hoặc thay đổi) điểm xuất phát/đích rồi chạy
  BFS/DFS/Dijkstra/UCS/Greedy/A* để quan sát sự khác nhau.
- Bảng kết quả hiển thị tổng chiều dài, số cạnh trên đường đi và danh sách chi
  tiết từng cạnh.
- Phần "Đồ thị GraphML" hiển thị thống kê số nút/cạnh, bản xem trước GraphML,
  nút tải xuống file `.graphml` và công tắc ẩn/hiện nền bản đồ để bạn nhìn rõ
  cấu trúc đồ thị thuần túy.
- Các khu vực bị ngập, tắc hoặc bị cấm đã được admin giao thông thay đổi.

## Sử dụng script CLI

Ví dụ chạy tìm đường bằng A* giữa hai địa điểm tại Hà Nội :

python pathfinding.py \
  --place "Khuong Dinh, Thanh Xuan, Hanoi, Vietnam" \
  --start "20.9945,105.8150" \
  --goal "20.9970,105.8180" \
  --algorithm astar \
  --output khuong_dinh_astar.html

### Tham số chính

- `--place`: Tên địa danh để tải đường sá từ OpenStreetMap.
- `--center` + `--dist`: Tải khu vực xung quanh một tọa độ trung tâm (theo mét).
- `--start`, `--goal`: Địa chỉ (sẽ được geocode) hoặc cặp `lat,lon`.
- `--algorithm`: `bfs`, `dfs`, `dijkstra`, `ucs`, `greedy`, `astar` (mặc định `astar`).
- `--block-street`: Chọn hai node liền kề tạo thành các đoạn bị chặn
- `--flood-zone`: Chuỗi các node liền kề tạo thành các đoạn bị ngập
- `--penalize-street`: Tăng hệ số chi phí cho toàn bộ cạnh thuộc một tuyến
  đường, cú pháp `Tên đường:hệ số`. Ví dụ `--penalize-street "Giải Phóng:1.8"`
  sẽ khiến các cạnh trên đường Giải Phóng bị phạt gấp 1.8 lần chiều dài.
- `--penalize-osmid`: Tăng hệ số chi phí dựa trên `osmid` của cạnh từ
  OpenStreetMap, cú pháp `OSMID:hệ số`.
- `--output`: Đường dẫn file HTML để lưu bản đồ.
- `--result-json`: (Tùy chọn) Lưu thông tin đường đi ở dạng JSON.
- `--graphml-output`: (Tùy chọn) Xuất đồ thị (gồm các thuộc tính `length`,
  `cost`, `penalty_multiplier`, `blocked`) sang GraphML.
- `--graphml-active`: Khi dùng chung với `--graphml-output`, loại bỏ các cạnh
  bị chặn trước khi ghi file (đồ thị chỉ còn các cạnh có thể đi được).

Sau khi chạy, file HTML có thể được mở trong trình duyệt để quan sát trực quan
đường đi và các chướng ngại.

## Ghi chú

- Các thuật toán BFS/DFS không tối ưu cho đường có trọng số, vì vậy kết quả
  chủ yếu để minh họa sự khác biệt với các thuật toán tối ưu như Dijkstra và
  A*.
- Nếu không tìm được đường do chặn quá nhiều tuyến, script sẽ báo lỗi không có
  đường đi (`NetworkXNoPath`).
- Tổng chi phí trong kết quả sẽ bằng chiều dài sau khi nhân với hệ số phạt (nếu
  có). Các cạnh không bị phạt sẽ có `penalty_multiplier = 1.0`.
- Mã nguồn đã được cập nhật để tương thích với OSMnx 2.0.6; nếu dùng bản cũ
  hơn bạn cần hạ hệ số phụ thuộc hoặc đảm bảo có các API tương tự.
- Đồ thị xuất ra (cả trong giao diện lẫn GraphML) là `MultiDiGraph`, phản ánh
  các tuyến đường một chiều của OpenStreetMap.

## Trang admin (quản trị)
- Truy cập vào http://127.0.0.1:5000/admin để có thể đăng nhập để cập nhật tình hình giao thông cho các tuyến đường khu vực Khương Đình
- Ứng dụng cố định dữ liệu khu vực Khương Đình (Thanh Xuân, Hà Nội) từ GraphML offline, không tải nơi khác.
- Mở `/admin` sau khi chạy Flask. Đăng nhập bằng `ADMIN_USERNAME` và `ADMIN_PASSWORD` (mặc định `Dungdz0201` / `02012005` hoặc giá trị đặt qua biến môi trường). Chưa đăng nhập chỉ thấy form giữa màn hình.
- Sau khi đăng nhập mới hiện map và điều khiển: click 2 node liền kề để chọn đoạn đường, nhập hệ số phạt (>1) để tăng `cost` cho cả hai chiều. Nút Xóa bỏ hệ số đoạn. Các đoạn không có cost là các đoạn bị cấm.
- Hệ số chỉ lưu trong RAM: tắt server là reset. Người dùng trang chính tự động nhận hệ số mới khi gọi API (đều dùng chung đồ thị Khương Đình).
- Nền màn hình login đọc từ `static/bg-admin.jpg` (thay file này nếu muốn nền khác).
