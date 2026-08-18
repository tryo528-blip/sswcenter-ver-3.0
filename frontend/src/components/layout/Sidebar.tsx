import React from 'react';
import { NavLink } from 'react-router';
import { useAuthSafe } from '../../context/useAuth';
import { CANONICAL_SIDEBAR_ITEMS } from '../../design-system/tokens';

const SIDEBAR_ENGLISH_NAMES: Record<string, string> = {
  dashboard: 'Dashboard',
  recipients: 'Recipients',
  staff: 'Staff',
  'social-workers': 'Social Workers',
  copay: 'Copay',
  io: 'Import / Export',
  filebox: 'Files',
  settings: 'Settings',
};

const SIDEBAR_ICON_PATHS: Record<string, string> = {
  dashboard: 'M5 5h5v5H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h5v5h-5z',
  recipients:
    'M9 3.5a3.25 3.25 0 1 0 0 6.5 3.25 3.25 0 0 0 0-6.5ZM2.5 20.5v-1.2a6.5 6.5 0 0 1 13 0v1.2M18.5 14l-.95-.85c-1.05-.94-1.95-1.78-1.95-2.9a1.65 1.65 0 0 1 2.9-1.1 1.65 1.65 0 0 1 2.9 1.1c0 1.12-.9 1.96-1.95 2.9l-.95.85Z',
  staff:
    'M8.5 5a2.75 2.75 0 1 0 0 5.5 2.75 2.75 0 0 0 0-5.5ZM3.5 20.5v-1.2a5 5 0 0 1 10 0v1.2M17 8.5a2.5 2.5 0 1 0-1.5-4.5M15 13.5a4.75 4.75 0 0 1 5.5 4.7v2.3',
  'social-workers':
    'M9 3.5a3.25 3.25 0 1 0 0 6.5 3.25 3.25 0 0 0 0-6.5ZM2.5 20.5v-1.2a6.5 6.5 0 0 1 13 0v1.2M18.5 7v6M15.5 10h6',
  copay:
    'M4 8.5h14a2 2 0 0 1 2 2v8H5a2 2 0 0 1-2-2v-7a1 1 0 0 1 1-1ZM4 8.5V7a2 2 0 0 1 2-2h8.5M8.5 8.5a2.75 2.75 0 1 0 0-5.5 2.75 2.75 0 0 0 0 5.5ZM13 6.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM16 12h5v4h-5a2 2 0 1 1 0-4ZM17.5 14h.01',
  io: 'M3 8h15l-3-3M18 8l-3 3M21 16H7l3-3M7 16l3 3',
  filebox:
    'M4.5 6.5H10l2 2h7.5v10h-15zM4.5 8.5h15',
  settings:
    'M9 12.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5ZM9 10.5V12M9 18v1.5M4.5 15h2M11.5 15h2M5.8 11.8l1.4 1.4M10.8 16.8l1.4 1.4M12.2 11.8l-1.4 1.4M7.2 16.8l-1.4 1.4M16 5.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM16 4v1.5M16 9.5V11M12.5 7.5H14M18 7.5h1.5M13.5 5l1 1M17.5 9l1 1M18.5 5l-1 1M14.5 9l-1 1',
};

export const Sidebar: React.FC = () => {
  const { user, logout } = useAuthSafe();
  const visibleItems =
    user?.role_code === 'USER'
      ? CANONICAL_SIDEBAR_ITEMS.filter((item) => item.id !== 'settings')
      : CANONICAL_SIDEBAR_ITEMS;

  return (
    <aside className="app-sidebar" data-testid="app-sidebar">
      <div className="sidebar-header">
        <NavLink to="/dashboard" className="sidebar-brand" aria-label="Good Office Companion">
          <img
            className="sidebar-brand-mark"
            src="/whale_logo_transparent.png?v=2"
            alt=""
            aria-hidden="true"
          />
          <span className="sidebar-brand-copy">
            <strong>
              <span>Good Office</span>
              <span>Companion</span>
            </strong>
          </span>
        </NavLink>
      </div>

      <nav className="sidebar-nav">
        <ul className="sidebar-menu-list" role="menu">
          {visibleItems.map((item) => (
            <li key={item.id} className="sidebar-menu-item" role="none">
              <NavLink
                to={item.path}
                className={({ isActive }) => `sidebar-menu-link ${isActive ? 'active' : ''}`}
                role="menuitem"
                aria-label={item.label}
                data-testid={`sidebar-item-${item.id}`}
              >
                <svg
                  className={`sidebar-menu-icon ${item.id === 'settings' ? 'sidebar-menu-icon-settings' : ''} ${item.id === 'filebox' ? 'sidebar-menu-icon-filebox' : ''}`}
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  {item.id === 'copay' ? (
                    <g
                      fill="currentColor"
                      fontFamily="Arial, sans-serif"
                      fontSize="16"
                      fontWeight="400"
                      textAnchor="middle"
                    >
                      <text x="12" y="18">
                        ₩
                      </text>
                    </g>
                  ) : (
                    <path
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.35"
                      d={SIDEBAR_ICON_PATHS[item.id] || SIDEBAR_ICON_PATHS.dashboard}
                    />
                  )}
                </svg>
                <span className="sidebar-menu-label">{item.label}</span>
                <span className="sidebar-menu-label-en" aria-hidden="true">
                  {SIDEBAR_ENGLISH_NAMES[item.id] || item.label}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar-footer">
        <button className="sidebar-logout" type="button" data-testid="sidebar-logout" onClick={logout}>
          로그아웃
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
