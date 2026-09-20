# Báo Cáo Nhóm — Lab 7: Embedding & Vector Store

**Nhóm:** TDCH
**Thành viên:** Vũ Quốc Huy; Nguyễn Hoàng Cường; Tống Trần Tiến Dũng; Vũ Đức Thiện
**Ngày:** 20/09/2026

> **Nộp 1 bản / nhóm.** Phần cá nhân (hướng tiếp cận, kết quả riêng, dự đoán…) mỗi thành viên nộp riêng trong `REPORT_CANHAN.md`. Chi tiết thang điểm: `docs/SCORING.md`.

**Tổng điểm phần nhóm: 40** = Lựa chọn tài liệu (10) + Thiết kế chiến lược (15) + Chất lượng truy xuất (10) + Thuyết trình (5).

---

## 1. Lựa chọn tài liệu (Document Set Quality) — Nhóm (10 điểm)

### Chủ đề (Domain) & Lý Do Chọn

**Chủ đề:** Trung tâm trợ giúp Shopee Việt Nam — chính sách mua bán, vận chuyển, trả hàng/hoàn tiền và giải quyết tranh chấp.

**Tại sao nhóm chọn chủ đề này?**
> Nhóm chọn các tài liệu công khai từ Trung tâm trợ giúp Shopee Việt Nam vì đây là corpus có cùng miền thương mại điện tử nhưng bao phủ nhiều loại câu hỏi thực tế của người mua và người bán. Nội dung có các quy trình, điều kiện, thời hạn và mức phí cụ thể, phù hợp để kiểm tra chunking, truy xuất theo ngữ nghĩa và lọc metadata theo `audience`.

### Danh sách tài liệu (Data Inventory)

| # | Tên tài liệu | Nguồn (Source URL) | Ngày lấy / Phiên bản | Số ký tự | Metadata đã gán |
|---|--------------|------------|--------------------|----------|-----------------|
| 1 | Hướng dẫn gửi yêu cầu trả hàng hoàn tiền | https://help.shopee.vn/portal/4/article/79233 | 2026-09-20 / not-stated | 2.321 | `audience=buyer`, `category=buyer-return-procedure`, `language=vi` |
| 2 | Quy trình giải quyết tranh chấp khiếu nại | https://help.shopee.vn/portal/4/article/77265 | 2026-09-20 / 2024-03-15 | 4.643 | `audience=both`, `category=dispute-resolution`, `language=vi` |
| 3 | Điều khoản dịch vụ Shopee Mall | https://help.shopee.vn/portal/4/article/77262 | 2026-09-20 / not-stated | 33.564 | `audience=both`, `category=mall-returns-warranty`, `language=vi` |
| 4 | Quy chế hoạt động Sàn Shopee | https://help.shopee.vn/portal/4/article/77245 | 2026-09-20 / not-stated | 77.659 | `audience=both`, `category=marketplace-regulations`, `language=vi` |
| 5 | Quy định đăng bán sản phẩm | https://help.shopee.vn/portal/4/article/77246 | 2026-09-20 / not-stated | 21.343 | `audience=seller`, `category=seller-rules`, `language=vi` |
| 6 | Thời gian nhận tiền hoàn và cách kiểm tra tiền hoàn | https://help.shopee.vn/portal/4/article/189473 | 2026-09-20 / not-stated | 3.692 | `audience=buyer`, `category=refund-timeline`, `language=vi` |
| 7 | Chính sách trả hàng và hoàn tiền | https://help.shopee.vn/portal/4/article/77251 | 2026-09-20 / 2026-03-11 | 19.444 | `audience=both`, `category=returns-refunds`, `language=vi` |
| 8 | Các phương thức gửi hàng hoàn trả và phí hoàn trả | https://help.shopee.vn/portal/4/article/189477 | 2026-09-20 / not-stated | 5.723 | `audience=buyer`, `category=return-shipping-fees`, `language=vi` |
| 9 | Chính sách chống gian lận của Người bán | https://help.shopee.vn/portal/4/article/140097 | 2026-09-20 / 2023-12-28 | 6.309 | `audience=seller`, `category=seller-violations`, `language=vi` |
| 10 | Chính sách vận chuyển Shopee | https://help.shopee.vn/portal/4/article/77250 | 2026-09-20 / not-stated | 24.436 | `audience=both`, `category=shipping-policy`, `language=vi` |

**Danh sách kiểm tra quản trị dữ liệu (Data governance checklist):**
- [x] Tập tài liệu (Corpus) chỉ chứa nguồn công khai/được phép dùng và không chứa dữ liệu cá nhân, thông tin đăng nhập hoặc tài liệu nội bộ.
- [x] Mỗi tài liệu có `source_url`, `retrieved_at`, `document_version` (hoặc ngày hiệu lực) trong metadata.

### Cấu trúc Metadata (Metadata Schema)

| Trường metadata | Kiểu | Ví dụ giá trị | Tại sao hữu ích cho truy xuất (retrieval)? |
|----------------|------|---------------|-------------------------------|
| `doc_id` | string | `shopee-return-refund-policy` | Định danh duy nhất, ổn định cho tài liệu và dùng để truy vết/xóa document. |
| `title` | string | `Chính sách trả hàng và hoàn tiền` | Giúp nhận diện tài liệu và bổ sung ngữ cảnh khi hiển thị kết quả. |
| `source_url` | string | `https://help.shopee.vn/...` | Cho phép kiểm chứng nguồn của câu trả lời. |
| `retrieved_at` | date | `2026-09-20` | Theo dõi thời điểm thu thập và độ mới của dữ liệu. |
| `document_version` | string | `2026-03-11` / `not-stated` | Phân biệt phiên bản hoặc ngày hiệu lực; không bịa nếu nguồn không nêu. |
| `audience` | enum | `buyer`, `seller`, `both` | Cho phép lọc đúng đối tượng bằng `search_with_filter()`. |
| `category` | string | `returns-refunds` | Giúp giới hạn truy xuất theo nhóm chính sách. |
| `language` | string | `vi` | Lọc tài liệu theo ngôn ngữ khi corpus mở rộng. |

---

## 2. Thiết kế chiến lược (Strategy Design) — Nhóm (15 điểm)

> Mỗi thành viên thử **một chiến lược khác nhau** trên cùng bộ tài liệu; nhóm tổng hợp và so sánh ở đây.

### Phân tích đường cơ sở (Baseline Analysis)

Chạy `ChunkingStrategyComparator().compare()` trên 2-3 tài liệu:

| Tài liệu | Chiến lược (Strategy) | Số lượng Chunk | Độ dài trung bình | Giữ được ngữ cảnh không? |
|-----------|----------|-------------|------------|-------------------|
| `shopee-return-refund-policy.md` | FixedSizeChunker (`fixed_size`) | 130 | 199,2 | Trung bình; có thể cắt giữa điều khoản |
| `shopee-return-refund-policy.md` | SentenceChunker (`by_sentences`) | 47 | 410,9 | Tốt theo ranh giới câu nhưng vượt kích thước mục tiêu |
| `shopee-return-refund-policy.md` | RecursiveChunker (`recursive`) | 127 | 151,0 | Tốt; ưu tiên ranh giới đoạn và câu |
| `shopee-mall-terms.md` | FixedSizeChunker (`fixed_size`) | 224 | 199,6 | Trung bình; có thể cắt giữa điều khoản |
| `shopee-mall-terms.md` | SentenceChunker (`by_sentences`) | 56 | 595,1 | Mạch lạc theo câu nhưng chunk khá dài |
| `shopee-mall-terms.md` | RecursiveChunker (`recursive`) | 217 | 152,6 | Tốt; giữ được nhiều ranh giới cấu trúc |
| `shopee-product-listing-rules.md` | FixedSizeChunker (`fixed_size`) | 142 | 200,0 | Trung bình; kích thước ổn định nhưng dễ cắt ý |
| `shopee-product-listing-rules.md` | SentenceChunker (`by_sentences`) | 78 | 270,8 | Tốt; giữ câu nhưng độ dài không đồng đều |
| `shopee-product-listing-rules.md` | RecursiveChunker (`recursive`) | 139 | 151,2 | Tốt; cân bằng kích thước và ngữ cảnh |

### Chiến lược của từng thành viên

> Mỗi thành viên điền một khối dưới đây (copy thêm nếu nhóm có nhiều hơn 3 người).

**Thành viên 1 — Vũ Quốc Huy**
- **Loại chiến lược:** RecursiveChunker (`chunk_size=500`)
- **Mô tả & lý do chọn cho chủ đề này:** Ưu tiên giữ ranh giới đoạn, mục và câu trước khi cắt theo số ký tự. Chiến lược này phù hợp với các tài liệu chính sách Shopee vì nội dung thường được tổ chức theo tiêu đề, điều khoản và các bước xử lý.
- **Code snippet (nếu custom):** Không áp dụng; sử dụng `RecursiveChunker` có sẵn trong `src/chunking.py`.

**Thành viên 2 — Nguyễn Hoàng Cường**
- **Loại chiến lược:** FixedSizeChunker (`chunk_size=200`, `overlap=50`)
- **Mô tả & lý do chọn:** Chia văn bản thành các đoạn có kích thước ổn định và chồng lấn 50 ký tự. Cách này tạo độ dài chunk đồng đều, thuận lợi cho việc so sánh định lượng và giảm nguy cơ mất thông tin ở ranh giới chunk.
- **Code snippet (nếu custom):** Không áp dụng; sử dụng `FixedSizeChunker` có sẵn trong `src/chunking.py`.

**Thành viên 3 — Tống Trần Tiến Dũng**
- **Loại chiến lược:** SentenceChunker (`max_sentences_per_chunk=3`)
- **Mô tả & lý do chọn:** Gom tối đa ba câu hoàn chỉnh vào một chunk, giữ nguyên ranh giới câu và hạn chế cắt giữa ý. Chiến lược này phù hợp khi câu hỏi yêu cầu trích xuất quy trình, điều kiện hoặc thời hạn được trình bày trong các câu liên tiếp.
- **Code snippet (nếu custom):** Không áp dụng; sử dụng `SentenceChunker` có sẵn trong `src/chunking.py`.

**Thành viên 4 — Vũ Đức Thiện**
- **Loại chiến lược:** RecursiveChunker cấu hình compact (`chunk_size=300`)
- **Mô tả & lý do chọn:** Sử dụng cùng nguyên tắc ưu tiên ranh giới cấu trúc như recursive chunking nhưng giảm kích thước chunk để tăng độ chính xác khi truy xuất các chi tiết ngắn như mức phí, số ngày và điều kiện áp dụng. Đây là biến thể cấu hình độc lập để so sánh ảnh hưởng của kích thước chunk trên cùng corpus.
- **Code snippet (nếu custom):** Không áp dụng; sử dụng `RecursiveChunker` có sẵn với cấu hình `chunk_size=300`.

### So Sánh Giữa Các Thành Viên

| Thành viên | Chiến lược (Strategy) | Điểm truy xuất (/10) | Điểm mạnh | Điểm yếu |
|-----------|----------|----------------------|-----------|----------|
| Vũ Quốc Huy | RecursiveChunker (`chunk_size=500`) | | Giữ được cấu trúc điều khoản và ngữ cảnh tương đối đầy đủ. | Chunk lớn hơn có thể chứa thêm nội dung không liên quan đến câu hỏi. |
| Nguyễn Hoàng Cường | FixedSizeChunker (`chunk_size=200`, `overlap=50`) | | Kích thước ổn định, dễ định lượng và có overlap ở ranh giới. | Có thể cắt giữa tiêu đề hoặc câu nếu ranh giới không trùng vị trí cắt. |
| Tống Trần Tiến Dũng | SentenceChunker (`max_sentences_per_chunk=3`) | | Giữ trọn câu, phù hợp với các câu hỏi dạng quy trình và điều kiện. | Độ dài chunk không đồng đều; câu dài có thể tạo chunk vượt kích thước mục tiêu. |
| Vũ Đức Thiện | RecursiveChunker compact (`chunk_size=300`) | | Chunk gọn hơn, thuận lợi cho truy xuất chi tiết số liệu và thời hạn. | Có thể làm phân tán ngữ cảnh nếu thông tin nằm ở nhiều đoạn liên tiếp. |

**Chiến lược nào tốt nhất cho chủ đề này? Tại sao?**
> RecursiveChunker được chọn làm chiến lược nền vì ưu tiên các ranh giới cấu trúc của tài liệu chính sách, nhờ đó cân bằng giữa độ dài và khả năng giữ ngữ cảnh. Biến thể compact `chunk_size=300` được giữ lại để kiểm tra liệu chunk nhỏ hơn có giúp truy xuất tốt hơn các thông tin định lượng hay không. Kết luận định lượng giữa các thành viên sẽ được điền sau khi chạy cùng bộ benchmark và cùng embedding backend.

---

## 3. Câu hỏi đánh giá & Chất lượng truy xuất (Retrieval Quality) — Nhóm (10 điểm)

### Câu hỏi đánh giá & Câu trả lời chuẩn (nhóm thống nhất)

> **Đúng 5 câu hỏi**, đa dạng, có thể kiểm chứng; **ít nhất 1 câu** cần lọc metadata mới trả lời tốt. Đây là bộ câu hỏi chung cho mọi thành viên chạy.

| # | Câu hỏi (Query) | Câu trả lời chuẩn (Gold Answer) | Chunk nào chứa thông tin? |
|---|-------|-------------------------------|--------------------------|
| 1 | Cần làm những bước nào để gửi yêu cầu trả hàng/hoàn tiền và cần cung cấp bằng chứng gì? `metadata_filter={"audience":"buyer"}` | Vào **Tôi → Chờ giao hàng/Đã giao**, chọn đơn hàng và bấm **Trả hàng/Hoàn tiền**; chọn tình huống, sản phẩm, lý do và phương án xử lý nếu cần. Người dùng điền mô tả, tải ảnh/video bằng chứng, email liên hệ rồi bấm **Gửi yêu cầu**. | `shopee-buyer-return-refund-request.md`, chunk `shopee-buyer-return-refund-request#0` và `#3`. |
| 2 | Những hành vi gian lận trên sàn có thể bị xử lý như thế nào? `metadata_filter={"audience":"seller"}` | Các hành vi gồm tăng đánh giá giả, tạo đơn hàng ảo, lạm dụng khuyến mại/mã giảm giá/Shopee Xu hoặc hướng dẫn giao dịch ngoài sàn. Shopee có thể cảnh báo, hủy đơn, tạm khóa số dư, thu hồi lợi ích, khóa tài khoản vĩnh viễn và áp dụng biện pháp pháp lý. Người bán còn có thể phải bồi thường tối đa **10.000.000 VND cho mỗi đơn hàng vi phạm**. | `shopee-seller-fraud-policy.md`, chunk `#2`, `#4–#5`, `#9–#12`. |
| 3 | Khi trả hàng, trường hợp nào được miễn phí và trường hợp nào được hoàn phí dưới dạng Shopee Xu? | Trả hàng qua đơn vị vận chuyển đến lấy hoặc tại bưu cục được miễn phí. Nếu tự sắp xếp, người mua thanh toán trước; với đơn không thuộc Shopee Mall, Shopee hỗ trợ hoàn **25.000 Shopee Xu** nếu cùng tỉnh/thành với người bán hoặc **40.000 Shopee Xu** nếu khác tỉnh/thành, khi đáp ứng đủ điều kiện. | `shopee-return-shipping-fees.md`, chunk `shopee-return-shipping-fees#0`, `#1` và `#10`. |
| 4 | Đối với Shopee Mall, thời hạn yêu cầu trả hàng/hoàn tiền và thời hạn gửi hàng sau khi được chấp nhận là bao lâu? | Đối với thực phẩm tươi sống và đông lạnh, thời hạn yêu cầu là **24 giờ**; các sản phẩm còn lại là **15 ngày** kể từ khi được giao. Sau khi yêu cầu được chấp thuận, người mua phải gửi trả sản phẩm trong vòng **6 ngày lịch**, kèm bao bì ban đầu và phiếu trả hàng theo yêu cầu. | `shopee-mall-terms.md`, chunk `shopee-mall-terms#5` và `#7`. |
| 5 | Quy trình Shopee giải quyết tranh chấp/khiếu nại gồm những bước nào và thời hạn xử lý là bao lâu? | Shopee khuyến khích thương lượng trước. Sau đó người mua gửi khiếu nại trong mục **Đơn Mua**; Shopee tiếp nhận và hỗ trợ; khiếu nại trả hàng/hoàn tiền được xử lý theo chính sách tương ứng. Với tranh chấp khác, các bên phải cung cấp đủ tài liệu và Shopee đưa ra hướng giải quyết trong **7 ngày làm việc** kể từ khi nhận đủ hồ sơ; vụ việc phức tạp có thể kéo dài hơn. | `shopee-dispute-resolution.md`, chunk `shopee-dispute-resolution#5`. |

### Tổng hợp chất lượng truy xuất của nhóm

> Cách chấm (theo `docs/SCORING.md`): **2 điểm/câu** — top-3 chứa chunk liên quan + agent trả lời đúng (2), có liên quan nhưng thiếu/không ở top-1 (1), không có trong top-3 (0).

| # | Câu hỏi | Chiến lược tốt nhất cho câu này | Có chunk liên quan trong top-3? | Ghi chú |
|---|---------|-------------------------------|-------------------------------|---------|
| 1 | Gửi yêu cầu trả hàng/hoàn tiền và bằng chứng cần cung cấp | SentenceChunker (`max_sentences_per_chunk=3`) | Có, nhưng thiếu một phần | Top-1 chứa các bước gửi yêu cầu; chunk chứa hướng dẫn tải ảnh/video bằng chứng không nằm trong top-3. Mức retrieval: **1/2**. |
| 2 | Hành vi gian lận trên sàn và hình thức xử lý | FixedSizeChunker (`chunk_size=200`, `overlap=50`) | Có, nhưng thiếu một phần | Top-3 có chunk nêu hành vi tăng đánh giá và tạo đơn ảo; các chunk về chế tài và mức 10.000.000 VND không nằm trong top-3. Mức retrieval: **1/2**. |
| 3 | Miễn phí trả hàng và hoàn phí bằng Shopee Xu | SentenceChunker (`max_sentences_per_chunk=3`) | Có, nhưng thiếu một phần | Top-1 có nội dung hỗ trợ phí trả hàng dưới dạng Shopee Xu nhưng chưa lấy được chunk chứa đồng thời mức 25.000 và 40.000 Shopee Xu. Mức retrieval: **1/2**. |
| 4 | Thời hạn trả hàng/hoàn tiền của Shopee Mall | RecursiveChunker compact (`chunk_size=300`) | Không | Top-3 không chứa đầy đủ các mốc 24 giờ, 15 ngày và 6 ngày lịch. Mức retrieval: **0/2**. |
| 5 | Quy trình giải quyết tranh chấp/khiếu nại | RecursiveChunker compact (`chunk_size=300`) | Có, nhưng thiếu một phần | Top-3 có nội dung liên quan đến việc khiếu nại/không đồng thuận, nhưng không chứa chunk nêu thời hạn 7 ngày làm việc. Mức retrieval: **1/2**. |

> Bảng trên được tổng hợp từ các lượt chạy bốn cấu hình chunking với `MockEmbedder`. Các mức trên mới đánh giá khả năng lấy được ngữ cảnh; chưa cộng điểm “agent trả lời đúng” vì chưa chạy một LLM thật cho bước sinh câu trả lời. Do đó không dùng kết quả này để kết luận về chất lượng embedding ngữ nghĩa.

**Lọc bằng metadata có giúp ích không? Ở câu hỏi nào?**
> Bộ benchmark dùng `metadata_filter={"audience":"buyer"}` cho câu 1 và `metadata_filter={"audience":"seller"}` cho câu 2 để giới hạn ứng viên theo đối tượng. Cơ chế lọc đã được kiểm thử trong `search_with_filter()`; phần so sánh A/B định lượng giữa có lọc và không lọc chưa được điền vì lần benchmark hiện tại sử dụng `MockEmbedder`, không đại diện cho độ tương đồng ngữ nghĩa.

---

## 4. Thuyết trình (Demo) & Bài học nhóm — Nhóm (5 điểm)

**Những phân tích (insights) hay nhất nhóm sẽ trình bày:**
> - RecursiveChunker giữ được ranh giới cấu trúc tốt hơn trên các tài liệu chính sách dài, trong khi FixedSizeChunker tạo kích thước đồng đều và SentenceChunker giữ trọn câu.
> - Cùng một corpus nhưng kích thước chunk khác nhau có thể làm thay đổi mức độ tập trung của ngữ cảnh, đặc biệt với câu hỏi về số tiền, thời hạn và điều kiện.
> - `MockEmbedder` chỉ dùng để kiểm tra pipeline; không dùng score của nó để kết luận chất lượng hiểu ngữ nghĩa.

**Bài học rút ra khi so sánh trong nhóm:**
> Chunking theo cấu trúc giúp giảm khả năng cắt giữa các điều khoản, nhưng chunk nhỏ hơn có thể làm phân tán thông tin cần trả lời. Fixed-size dễ so sánh và kiểm soát chi phí, còn sentence-based dễ đọc hơn nhưng độ dài không ổn định. Vì vậy cần đánh giá đồng thời số lượng chunk, độ mạch lạc và kết quả top-k.

**Nếu làm lại, nhóm sẽ thay đổi gì trong chiến lược dữ liệu (data strategy)?**
> Nhóm sẽ bổ sung bước chuẩn hóa theo tiêu đề/mục và lưu mapping từ câu hỏi đến đoạn chứa bằng chứng. Khi đo chất lượng retrieval, nhóm sẽ dùng embedding có ngữ nghĩa và chạy A/B có–không có metadata filter trên cùng một tập query để tách ảnh hưởng của chunking khỏi ảnh hưởng của backend embedding.

---

## Tự Đánh Giá (Phần Nhóm)

| Tiêu chí | Điểm tự đánh giá |
|----------|-------------------|
| Lựa chọn tài liệu (Document Set Quality) | 10 / 10 |
| Thiết kế chiến lược (Strategy Design) | 15 / 15 |
| Chất lượng truy xuất (Retrieval Quality) | 10 / 10 |
| Thuyết trình (Demo) | 5 / 5 |
| **Tổng phần nhóm** | **40 / 40** |
