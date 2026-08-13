import type {
  OfficialWorkCard,
  OfficialWorkCardCollection,
} from '../../services/w2Api';

export function formatOfficialDday(value: number): string {
  if (value === 0) return 'D-DAY';
  return value > 0 ? `D-${value}` : `D+${Math.abs(value)}`;
}

function WorkCard({
  card,
  readOnly,
  closing,
  onClose,
}: {
  card: OfficialWorkCard;
  readOnly: boolean;
  closing: boolean;
  onClose: (card: OfficialWorkCard) => void;
}) {
  return (
    <article className="dashboard-official-card" data-testid="official-work-card">
      <dl className="dashboard-official-card-fields">
        <div><dt>업무제목</dt><dd>{card.title}</dd></div>
        <div><dt>대상자이름</dt><dd>{card.targetName || '미입력'}</dd></div>
        <div><dt>상세업무</dt><dd>{card.detail || '—'}</dd></div>
        <div><dt>마감일</dt><dd>{card.dueDate || '—'}</dd></div>
        <div><dt>D-day</dt><dd>{formatOfficialDday(card.dDay)}</dd></div>
      </dl>
      {!readOnly && (
        <div className="dashboard-official-card-controls" aria-label="카드 제어">
          <button type="button" disabled={closing} onClick={() => onClose(card)}>
            {closing ? '처리 중…' : '닫기'}
          </button>
        </div>
      )}
    </article>
  );
}

export function OfficialWorkCards({
  collection,
  readOnly,
  showStaffGroups,
  closingId,
  onClose,
}: {
  collection: OfficialWorkCardCollection;
  readOnly: boolean;
  showStaffGroups: boolean;
  closingId: number | null;
  onClose: (card: OfficialWorkCard) => void;
}) {
  const cardCount = collection.groups.reduce((sum, group) => sum + group.cards.length, 0);

  return (
    <section className="dashboard-work-block" aria-label="공식 업무카드">
      <div className="dashboard-work-heading">
        <h2>공식 업무카드</h2>
      </div>
      {cardCount === 0 ? (
        <p className="dashboard-work-empty">열린 업무카드가 없습니다.</p>
      ) : (
        <div className="dashboard-official-groups">
          {collection.groups.map((group, groupIndex) => (
            <section className="dashboard-official-group" key={`${group.staffId}-${groupIndex}`}>
              {showStaffGroups && (
                <h3 className="dashboard-official-staff-name">{group.staffName || '미입력'}</h3>
              )}
              <div className="dashboard-work-area">
                {group.cards.map((card) => (
                  <WorkCard
                    card={card}
                    closing={closingId === card.id}
                    key={card.id}
                    onClose={onClose}
                    readOnly={readOnly}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
