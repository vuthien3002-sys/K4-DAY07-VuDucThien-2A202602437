# Báo Cáo Cá Nhân — Lab 7: Embedding & Vector Store

**Họ tên:** [Vũ Đức Thiện]
**Nhóm:** [TDCH]
**Ngày:** [20/09/2026]

> **Nộp 1 bản / sinh viên.** Phần nhóm (lựa chọn tài liệu, thiết kế chiến lược, bộ câu hỏi đánh giá, demo) nộp chung 1 bản trong `REPORT_NHOM.md`. Chi tiết thang điểm: `docs/SCORING.md`.

**Tổng điểm phần cá nhân: 60** = Khởi động (5) + Hướng tiếp cận (10) + Hoàn thiện code (30) + Dự đoán độ tương tự (5) + Kết quả truy xuất của tôi (10).

---

## 1. Khởi động (Warm-up) — Cá nhân (5 điểm)

### Độ tương tự Cosine (Cosine Similarity) (Bài tập 1.1)

**Độ tương tự cosine cao (High cosine similarity) nghĩa là gì?**
Hai vector embedding có hướng gần nhau, nên hai đoạn văn có xu hướng nói về nội dung tương tự. Giá trị càng gần 1 thì mức tương đồng về hướng càng cao.

**Ví dụ có độ tương tự CAO:**
- Câu A: Người mua có thể yêu cầu hoàn tiền khi sản phẩm bị lỗi.
- Câu B: Khách hàng được phép gửi yêu cầu hoàn tiền nếu hàng không hoạt động.
- Tại sao tương đồng: Cùng nói về người mua, sản phẩm lỗi và hoàn tiền.

**Ví dụ có độ tương tự THẤP:**
- Câu A: Người bán phải phản hồi yêu cầu trả hàng.
- Câu B: Python là một ngôn ngữ lập trình.
- Tại sao khác: Hai câu thuộc hai chủ đề chính sách và lập trình khác nhau.

**Tại sao độ tương tự cosine (cosine similarity) được ưu tiên hơn khoảng cách Euclid (Euclidean distance) cho text embeddings?**
Cosine tập trung vào hướng của vector thay vì độ lớn tuyệt đối, phù hợp hơn khi độ dài văn bản khác nhau. Với embedding đã chuẩn hóa, dot product cũng chính là cosine similarity.

### Bài toán tính toán Chunking (Bài tập 1.2)

**Tài liệu 10,000 ký tự, chunk_size=500, overlap=50. Bao nhiêu chunks?**
`ceil((10000 - 50) / (500 - 50)) = ceil(9950 / 450) = 23` chunks.

**Nếu độ chồng chéo (overlap) tăng lên 100, số lượng chunk thay đổi thế nào? Tại sao muốn độ chồng chéo nhiều hơn?**
`ceil((10000 - 100) / (500 - 100)) = ceil(9900 / 400) = 25` chunks. Overlap lớn hơn giúp giữ ngữ cảnh ở ranh giới giữa hai chunk, nhưng làm tăng số chunk và chi phí embedding/retrieval.

---

## 2. Hướng tiếp cận của tôi (My Approach) — Cá nhân (10 điểm)

Giải thích cách tiếp cận của bạn khi lập trình (implement) các phần chính trong gói `src`.

### Các hàm chia nhỏ (Chunking Functions)

**`SentenceChunker.chunk`** — hướng tiếp cận:
Tách sau các dấu `.`, `!`, `?` khi theo sau là khoảng trắng bằng lookbehind để giữ lại dấu câu, sau đó gom tối đa số câu cấu hình trong một chunk. Text rỗng trả về danh sách rỗng. Edge case còn hạn chế là chữ viết tắt như `TS.` và số thập phân có thể bị nhận diện như ranh giới câu.

**`RecursiveChunker.chunk` / `_split`** — hướng tiếp cận:
Thử separator theo thứ tự paragraph, newline, sentence, space; mảnh vượt kích thước sẽ đệ quy xuống separator nhỏ hơn. Các mảnh liền kề được gom lại trước khi trả về để tránh chunk quá vụn. Base case là mảnh đã nhỏ hơn giới hạn hoặc fallback cắt cứng khi hết separator.

### Lớp EmbeddingStore

**`add_documents` + `search`** — hướng tiếp cận:
Mỗi `Document` được chuẩn hóa thành record gồm id, content, metadata và embedding rồi lưu trong in-memory store. Search embed query, tính dot product với từng record và sắp xếp giảm dần; embedding mock đã chuẩn hóa nên dot product tương đương cosine.

**`search_with_filter` + `delete_document`** — hướng tiếp cận:
Metadata được lọc trước khi tính similarity để các slot top-k không bị chiếm bởi tài liệu sai audience. `delete_document` xóa mọi record có `metadata['doc_id']` bằng id tài liệu gốc và trả về trạng thái có xóa được hay không.

### Tác tử KnowledgeBaseAgent

**`answer`** — hướng tiếp cận:
Agent retrieve top-k chunks, đánh số từng context kèm nguồn/metadata, rồi yêu cầu LLM chỉ dùng context và trích dẫn số chunk khi có thể. Khi store rỗng, agent trả thông báo không tìm thấy thay vì gọi LLM vô ích.

---

## 3. Hoàn thiện code (Core Implementation) — Cá nhân (30 điểm)

Vượt qua bộ kiểm thử là điều kiện tính điểm phần này.

### Kết Quả Kiểm Thử (Test Results)

```
# Dán kết quả (output) của: pytest tests/ -v
```

**Số lượng bài test vượt qua (pass):** 42 / 42

Kết quả chạy thực tế: `42 passed in 0.50s`.

---

## 4. Dự đoán độ tương tự (Similarity Predictions) — Cá nhân (5 điểm)

| Cặp | Câu A | Câu B | Dự đoán | Điểm thực tế | Đúng? |
|------|-----------|-----------|---------|--------------|-------|
| 1 | Chính sách đổi trả của người mua | Quy định trả hàng dành cho người mua | thấp | -0.204615 | Có |
| 2 | Người bán phải phản hồi trong 2 ngày | Người bán có nghĩa vụ phản hồi trong 2 ngày | thấp | -0.103379 | Có |
| 3 | Thời gian hoàn tiền là 14 ngày | Python là ngôn ngữ lập trình | thấp | -0.136748 | Có |
| 4 | Sản phẩm còn tem bảo hành | Đơn hàng chưa nhận được | thấp | -0.010601 | Có |
| 5 | Người mua gửi yêu cầu hoàn tiền | Người bán tiếp nhận yêu cầu hoàn tiền | cao | 0.101279 | Có |

**Kết quả nào bất ngờ nhất? Điều này nói gì về cách embeddings biểu diễn ý nghĩa?**
Các điểm trên được tính bằng `MockEmbedder`, một embedder băm chuỗi để phục vụ unit test nên không phản ánh ngữ nghĩa thật. Điều bất ngờ là những câu rõ ràng cùng chủ đề vẫn có thể có điểm âm hoặc thấp; vì vậy không được dùng mock để kết luận chiến lược retrieval.

---

## 5. Kết quả truy xuất của tôi (Competition Results) — Cá nhân (10 điểm)

Chạy **5 câu hỏi đánh giá của nhóm** trên mã nguồn cá nhân của bạn trong gói `src`. **5 câu hỏi này phải trùng với các thành viên cùng nhóm** (xem `REPORT_NHOM.md`).

| # | Câu hỏi (Query) | Top-1 Chunk truy xuất được (tóm tắt) | Điểm Score | Có liên quan không? (Relevant) | Câu trả lời của Agent (tóm tắt) |
|---|-------|--------------------------------|-------|-----------|------------------------|
| 1 | Thời hạn trả hàng/hoàn tiền? | `buyer-return-window#0` | 0.844 | Có, gold ở top-1 | Agent có context chứa mốc 15 ngày |
| 2 | Người bán phản hồi trong bao lâu? | `seller-return-response#0` | 0.844 | Có, gold ở top-1 | Agent có context chứa mốc 02 ngày lịch |
| 3 | Thời gian nhận tiền hoàn? | `refund-request-process#1` | 0.824 | Có, gold ở top-1 | Agent có context chứa mốc 1–14 ngày làm việc |
| 4 | Điều kiện bảo hành? | `warranty-conditions#0` | 0.886 | Có, gold ở top-1 | Agent có context chứa các điều kiện bảo hành |
| 5 | Ai chịu phí vận chuyển hoàn trả? | `return-shipping-costs#0` | 0.864 | Có, gold ở top-1 | Agent có context nêu trách nhiệm người bán |

**Bao nhiêu câu hỏi trả về chunk có liên quan trong top-3?** 5 / 5 với fixed-size + `gemini-embedding-001`; cả 5 gold chunks đều ở top-1.

**Điều hay nhất tôi học được từ thành viên khác / nhóm khác (qua demo):**
Không nên đánh giá retrieval chỉ bằng điểm score hoặc `doc_id`. Dù Gemini embedding cho kết quả 5/5 trên corpus hiện tại, vẫn cần kiểm tra chunk có chứa đúng điều kiện/mốc thời gian của gold answer và kiểm tra thêm ảnh hưởng của metadata filter.

---

## Tự Đánh Giá (Phần Cá Nhân)

| Tiêu chí | Điểm tự đánh giá |
|----------|-------------------|
| Khởi động (Warm-up) | / 5 |
| Hướng tiếp cận của tôi (My Approach) | / 10 |
| Hoàn thiện code (Core Implementation — tests) | / 30 |
| Dự đoán độ tương tự (Similarity Predictions) | / 5 |
| Kết quả truy xuất của tôi (Competition Results) | / 10 |
| **Tổng phần cá nhân** | **/ 60** |
