import React from 'react';
import { useHudiyTheme } from '../hooks/useHudiyTheme';

interface KeypadProps {
    value: string;
    onChange: (val: string) => void;
    onClose: () => void;
    onSubmit?: (val: string) => void;
}

export function Keypad({ value, onChange, onClose, onSubmit }: KeypadProps) {
    const { theme } = useHudiyTheme(null); // Socket not strictly needed for just reading scheme

    const handleKey = (k: string) => {
        if (value.length < 3) {
            onChange(value + k);
        }
    };

    const handleDel = () => {
        onChange(value.slice(0, -1));
    };

    const handleIncrement = (dir: number) => {
        const num = parseInt(value || '0');
        const nextVal = Math.max(0, num + dir).toString();
        onChange(nextVal);
        if (onSubmit) {
            onSubmit(nextVal);
        }
    };

    const btnBaseStyle: React.CSSProperties = {
        padding: '10px 0',
        fontSize: '24px',
        fontWeight: 'bold',
        borderRadius: '10px',
        border: 'none',
        backgroundColor: theme.surfaceDim || '#2a2a2a',
        color: theme.onSurface || '#fff',
        cursor: 'pointer',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        transition: 'background-color 0.1s'
    };

    return (
        <div
            style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: theme.surfaceContainer, //sad
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                zIndex: 100,
                borderRadius: '16px'
            }}
            onClick={onClose}
        >
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gridTemplateRows: 'repeat(4, 1fr)',
                    gap: '10px',
                    padding: '15px',
                    width: '95%',
                    maxWidth: '380px',
                    backgroundColor: theme.surfaceContainer || '#1e1e1e',
                    borderRadius: '16px',

                }}
                onClick={e => e.stopPropagation()}
            >
                {/* Row 1 */}
                <button onClick={() => handleKey('1')} style={btnBaseStyle}>1</button>
                <button onClick={() => handleKey('2')} style={btnBaseStyle}>2</button>
                <button onClick={() => handleKey('3')} style={btnBaseStyle}>3</button>
                <button onClick={() => handleIncrement(1)} style={{ ...btnBaseStyle, gridRow: 'span 2', backgroundColor: theme.secondaryFixed || '#3a3a3a', color: theme.onSecondaryContainer || '#000' }}>
                    <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="18 15 12 9 6 15"></polyline>
                    </svg>
                </button>

                {/* Row 2 */}
                <button onClick={() => handleKey('4')} style={btnBaseStyle}>4</button>
                <button onClick={() => handleKey('5')} style={btnBaseStyle}>5</button>
                <button onClick={() => handleKey('6')} style={btnBaseStyle}>6</button>

                {/* Row 3 */}
                <button onClick={() => handleKey('7')} style={btnBaseStyle}>7</button>
                <button onClick={() => handleKey('8')} style={btnBaseStyle}>8</button>
                <button onClick={() => handleKey('9')} style={btnBaseStyle}>9</button>
                <button onClick={() => handleIncrement(-1)} style={{ ...btnBaseStyle, gridRow: 'span 2', backgroundColor: theme.secondaryFixed || '#3a3a3a', color: theme.onSecondaryContainer || '#000' }}>
                    <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>

                {/* Row 4 */}
                <button onClick={handleDel} style={{ ...btnBaseStyle, backgroundColor: theme.surfaceTint || '#444', color: theme.onPrimary || '#fff' }}>
                    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"></path>
                        <line x1="18" y1="9" x2="12" y2="15"></line>
                        <line x1="12" y1="9" x2="18" y2="15"></line>
                    </svg>
                </button>
                <button onClick={() => handleKey('0')} style={btnBaseStyle}>0</button>
                <button onClick={onClose} style={{ ...btnBaseStyle, backgroundColor: theme.primary || '#d32f2f', color: theme.onPrimary || '#fff', fontSize: '1.2rem' }}>OK</button>
            </div>
        </div>
    );
}

