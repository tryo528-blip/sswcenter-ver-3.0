import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';

const copayRows = [
  ['홍길동', '162,400원', '162,400원', '완료'],
  ['김영자', '118,200원', '80,000원', '일부 수납'],
  ['최순자', '94,600원', '0원', '미수납'],
] as const;

export const CopayPage = () => (
  <EditorialPage
    testId="page-copay"
    className="copay-page"
    title="본인부담금"
  >
    <div className="feature-summary-grid">
      <div className="feature-summary"><span>청구</span><strong>4,820,600원</strong><p>48명</p></div>
      <div className="feature-summary"><span>수납</span><strong>4,192,400원</strong><p>42명</p></div>
      <div className="feature-summary"><span>미수납</span><strong>628,200원</strong><p>6명</p></div>
    </div>

    <EditorialCard title="8월 처리 상태" className="copay-workflow-card">
      <div className="workflow-line">
        <div className="workflow-step">일정 반영</div>
        <div className="workflow-step">금액 검토</div>
        <div className="workflow-step is-current">수납 확인</div>
        <div className="workflow-step">월 확정</div>
      </div>
    </EditorialCard>

    <EditorialCard title="수납 현황">
      <table className="editorial-table">
        <thead><tr><th>수급자</th><th>청구액</th><th>수납액</th><th>상태</th></tr></thead>
        <tbody>
          {copayRows.map(([name, billed, paid, status]) => (
            <tr key={name}><td>{name}</td><td>{billed}</td><td>{paid}</td><td><span className="editorial-status">{status}</span></td></tr>
          ))}
        </tbody>
      </table>
    </EditorialCard>
  </EditorialPage>
);

export default CopayPage;
