# Kết Quả Benchmark Gemini Embedding

**Ngày chạy:** 2026-09-19  
**Corpus:** 7 tài liệu chính sách Shopee, có filter metadata `audience`  
**Embedding backend:** `gemini-embedding-001` (3,072 chiều)  
**Top-k:** 3

## Tổng hợp theo chiến lược

| Chiến lược | Số chunks | Độ dài chunk trung bình | Gold chunk ở top-1 | Gold chunk trong top-3 |
|---|---:|---:|---:|---:|
| Fixed-size | 15 | 276.5 | 5 / 5 | 5 / 5 |
| Sentence | 16 | 234.1 | 5 / 5 | 5 / 5 |
| Recursive | 16 | 234.1 | 5 / 5 | 5 / 5 |
| Heading-aware | 16 | 256.1 | 5 / 5 | 5 / 5 |

## Top-1 theo bộ câu hỏi (Fixed-size)

| Câu hỏi | Top-1 gold chunk | Score |
|---|---|---:|
| Q1 — Thời hạn trả hàng/hoàn tiền | `buyer-return-window#0` | 0.844 |
| Q2 — Thời hạn phản hồi người bán | `seller-return-response#0` | 0.844 |
| Q3 — Thời gian nhận tiền hoàn | `refund-request-process#1` | 0.824 |
| Q4 — Điều kiện bảo hành | `warranty-conditions#0` | 0.886 |
| Q5 — Phí vận chuyển chiều hoàn | `return-shipping-costs#0` | 0.864 |

## Diễn giải

Trên tập corpus nhỏ và câu hỏi được thiết kế bám sát gold answer, cả bốn chiến lược đều truy xuất đúng gold chunk ở top-1. Vì vậy chưa thể kết luận một chiến lược vượt trội chỉ dựa trên recall@3. Khác biệt cần được đánh giá thêm bằng độ mạch lạc chunk, câu hỏi khó hơn và corpus lớn hơn.

Kết quả này dùng Gemini embedding thật; không so sánh trực tiếp với score từ MockEmbedder vì MockEmbedder không biểu diễn ngữ nghĩa.
