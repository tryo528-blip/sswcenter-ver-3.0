import { EditorialCard, EditorialPage } from '../components/common/EditorialPage';

const settings = [
  ['센터 한마디', '상단 공지 문구'],
  ['공휴일', '가산 계산 기준일'],
  ['로그인 계정', '직원 계정과 PIN'],
  ['감사 기록', '변경·조회 이력'],
  ['백업', '마지막 성공 08/02 01:00'],
] as const;

export const SettingsPage = () => (
  <EditorialPage testId="page-settings" className="settings-page" title="설정">
    <EditorialCard title="센터 설정">
      <div className="settings-list">
        {settings.map(([title, detail]) => (
          <div className="settings-row" key={title}>
            <h3>{title}</h3>
            <p>{detail}</p>
          </div>
        ))}
      </div>
    </EditorialCard>
  </EditorialPage>
);

export default SettingsPage;
