# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | CÓ | dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG (κ<0.6, R<0.7) | loại |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người đúng | Câu trả lời quá suồng sã ("anh check giúp em", "rồi nha"), vi phạm văn phong dịch vụ khách hàng chuẩn. Judge bỏ sót (FN). Cần bổ sung rubric cấm xưng hô suồng sã / teencode. |
| 2 | H-017 | PASS | FAIL | Người đúng | Chứa từ "bạn ơi", "rồi nha" không trang trọng đối với giao dịch tài chính. Judge bỏ sót (FN). Cần cập nhật prompt judge nhấn mạnh tính chuyên nghiệp của thông báo tiền bạc. |
| 3 | H-029 | PASS | FAIL | Người đúng | Giọng điệu cộc lốc, gắt gỏng ("không cần nhắn thêm"), gây ức chế cho khách hàng. Judge bỏ sót (FN). Rubric cần đưa các câu lệnh mệnh lệnh thô lỗ vào tiêu chí FAIL. |
| 4 | H-042 | FAIL | PASS | Người đúng | Câu thông báo rõ ràng, lịch sự ("Tiền về trong 3–5 ngày ạ"). Judge bắt lỗi quá đà (FP) do nhầm tưởng nhắc đến số ngày xử lý là thiếu lịch sự. |
| 5 | H-051 | FAIL | PASS | Người đúng | Câu trả lời ngắn gọn, đúng mực ("Dạ, LogiX đã refund..."). Judge đánh FAIL (FP) do dùng từ chêm tiếng Anh "refund". Nên điều chỉnh rubric cho phép các thuật ngữ quen thuộc. |

## Kết luận
- **Tiêu chí bị loại và lý do:** Loại bỏ `helpful` vì độ nhạy (Recall) chỉ đạt **0.300** và độ đồng thuận Cohen's $\kappa$ chỉ đạt **0.375**, thấp hơn nhiều so với ngưỡng sàn yêu cầu ($\kappa \ge 0.6, R \ge 0.7$). Ma trận nhầm lẫn của `helpful` là `{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}`, cho thấy judge bỏ sót tới 21/30 trường hợp không hữu ích (tỷ lệ bỏ sót lỗi 70%). Nếu dùng judge này làm gate sẽ tạo ra cảm giác an toàn giả tạo.
- **Rủi ro còn lại:** Judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng CSV); cần nhãn người mới trên dữ liệu sản xuất để có tập held-out đánh giá độc lập định kỳ.
