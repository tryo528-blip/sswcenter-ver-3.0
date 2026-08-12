import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';

const visits = [
  ['김영자', '박사회', '08/06', '예정'],
  ['홍길동', '이복지', '08/08', '확인 필요'],
  ['최순자', '박사회', '08/12', '예정'],
] as const;

export const SocialWorkersPage = () => (
  <EditorialPage
    testId="page-social-workers"
    className="social-workers-page"
    title="사회복지사"
  >
    <div className="feature-summary-grid">
      <div className="feature-summary"><span>이번 달 방문</span><strong>18 / 24</strong><p>6건 남음</p></div>
      <div className="feature-summary"><span>확인할 일정</span><strong>3</strong><p>오늘 1건</p></div>
      <div className="feature-summary"><span>휴가</span><strong>2</strong><p>이번 달</p></div>
    </div>

    <div className="editorial-main-rail">
      <EditorialCard title="방문 일정">
        <table className="editorial-table">
          <thead><tr><th>수급자</th><th>담당</th><th>방문일</th><th>상태</th></tr></thead>
          <tbody>
            {visits.map(([recipient, worker, date, status]) => (
              <tr key={recipient}><td>{recipient}</td><td>{worker}</td><td>{date}</td><td><span className="editorial-status">{status}</span></td></tr>
            ))}
          </tbody>
        </table>
      </EditorialCard>

      <EditorialCard title="휴가 일정">
        <ul className="editorial-list">
          <li><span>이복지 · 연차</span><span className="editorial-muted">08/09</span></li>
          <li><span>박사회 · 반차</span><span className="editorial-muted">08/14</span></li>
        </ul>
      </EditorialCard>
    </div>
  </EditorialPage>
);

export default SocialWorkersPage;
