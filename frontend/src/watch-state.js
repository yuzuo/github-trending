export const reviewLabels = { pending: '待测评', reviewing: '测评中', reviewed: '已测评', dismissed: '暂不考虑' }
export function growthLabel(growth) {
  return growth == null ? '积累中' : `${growth.delta > 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN').format(growth.delta)}`
}
export function reviewPayload(draft) {
  const rating = draft.rating === '' || draft.rating == null ? null : Number(draft.rating)
  if (!Object.hasOwn(reviewLabels, draft.review_status) || (rating !== null && (!Number.isInteger(rating) || rating < 1 || rating > 5))) throw new Error('请选择有效的测评状态和 1–5 分评分。')
  return { review_status: draft.review_status, rating, notes: draft.notes }
}
