import type { ReactNode } from 'react';

interface EditorialPageProps {
  testId: string;
  className?: string;
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}

interface EditorialCardProps {
  title: string;
  caption?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function EditorialPage({
  testId,
  className = '',
  eyebrow,
  title,
  description,
  action,
  children,
}: EditorialPageProps) {
  return (
    <div className={`editorial-page ${className}`.trim()} data-testid={testId}>
      <header className="editorial-page-heading">
        <div>
          {eyebrow ? <p className="editorial-eyebrow">{eyebrow}</p> : null}
          <div className="editorial-title-line">
            <h1>{title}</h1>
          </div>
          {description ? <p className="editorial-description">{description}</p> : null}
        </div>
        {action ? <div className="editorial-page-action">{action}</div> : null}
      </header>
      {children}
    </div>
  );
}

export function EditorialCard({
  title,
  caption,
  action,
  className = '',
  children,
}: EditorialCardProps) {
  return (
    <section className={`editorial-card ${className}`.trim()}>
      <header className="editorial-card-heading">
        <div>
          <h2>{title}</h2>
          {caption ? <p>{caption}</p> : null}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
