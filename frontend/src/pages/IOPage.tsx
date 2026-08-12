import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';

const importRows = [
  ['공단 급여계획', '08/02 09:14', '126건', '완료'],
  ['RFID 실제근무', '08/02 09:08', '94건', '3건 확인'],
  ['OCR 문서', '08/01 17:42', '12건', '2건 대기'],
] as const;

export const IOPage = () => (
  <EditorialPage
    testId="page-io"
    className="io-page"
    title="입출력"
  >
    <EditorialCard title="오늘 수집">
      <table className="editorial-table">
        <thead><tr><th>자료</th><th>시각</th><th>건수</th><th>상태</th></tr></thead>
        <tbody>
          {importRows.map(([source, time, count, status]) => (
            <tr key={source}><td>{source}</td><td>{time}</td><td>{count}</td><td><span className="editorial-status">{status}</span></td></tr>
          ))}
        </tbody>
      </table>
    </EditorialCard>
  </EditorialPage>
);

export default IOPage;
