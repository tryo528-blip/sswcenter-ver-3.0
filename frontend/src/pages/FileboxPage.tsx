import { EditorialPage } from '../components/common/EditorialPage';

const files = [
  ['8월 운영회의.pdf', 'PDF', '08/01'],
  ['시설 안전점검표.xlsx', 'XLSX', '07/31'],
  ['직원 교육대장.pdf', 'PDF', '07/29'],
] as const;

export const FileboxPage = () => (
  <EditorialPage
    testId="page-filebox"
    className="filebox-page"
    title="파일함"
  >
    <div className="filebox-browser">
      <aside className="filebox-pane filebox-folders">
        <h2>폴더</h2>
        <ul className="filebox-folder-list">
          <li className="is-active">기관 공용자료</li>
          <li>직원 서류</li>
          <li>수급자 서류</li>
          <li>정규 서류</li>
        </ul>
      </aside>

      <section className="filebox-pane">
        <h2>기관 공용자료</h2>
        <table className="editorial-table">
          <thead><tr><th>이름</th><th>형식</th><th>수정일</th></tr></thead>
          <tbody>
            {files.map(([name, type, date]) => <tr key={name}><td>{name}</td><td>{type}</td><td>{date}</td></tr>)}
          </tbody>
        </table>
      </section>

      <aside className="filebox-pane filebox-preview">
        <span>파일을 선택하세요.</span>
      </aside>
    </div>
  </EditorialPage>
);

export default FileboxPage;
