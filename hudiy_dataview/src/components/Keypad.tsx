import React from 'react';

interface KeypadProps {
    value: string;
    onChange: (val: string) => void;
    onClose: () => void;
    onSubmit?: (val: string) => void;
}

export function Keypad({ value, onChange, onClose, onSubmit }: KeypadProps) {
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

    return (
        <div
            style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: 'rgba(20, 20, 20, 0.95)',
                backdropFilter: 'blur(8px)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                zIndex: 100,
                borderRadius: '8px'
            }}
            onClick={onClose}
        >
            {/* Stop propagation so clicking buttons doesn't close it */}
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gridTemplateRows: 'repeat(4, 1fr)',
                    gap: '8px',
                    padding: '12px',
                    width: '95%',
                    maxWidth: '380px',
                    backgroundColor: 'rgba(255,255,255,0.05)',
                    borderRadius: '12px',
                    boxShadow: '0 10px 30px rgba(0,0,0,0.5)'
                }}
                onClick={e => e.stopPropagation()}
            >
                {/* Row 1 */}
                <button onClick={() => handleKey('1')} style={btnStyle}>1</button>
                <button onClick={() => handleKey('2')} style={btnStyle}>2</button>
                <button onClick={() => handleKey('3')} style={btnStyle}>3</button>
                <button onClick={() => handleIncrement(1)} style={{ ...btnStyle, gridRow: 'span 2', backgroundColor: '#3a3a3a', fontSize: '1.8rem' }}>▲</button>

                {/* Row 2 */}
                <button onClick={() => handleKey('4')} style={btnStyle}>4</button>
                <button onClick={() => handleKey('5')} style={btnStyle}>5</button>
                <button onClick={() => handleKey('6')} style={btnStyle}>6</button>

                {/* Row 3 */}
                <button onClick={() => handleKey('7')} style={btnStyle}>7</button>
                <button onClick={() => handleKey('8')} style={btnStyle}>8</button>
                <button onClick={() => handleKey('9')} style={btnStyle}>9</button>
                <button onClick={() => handleIncrement(-1)} style={{ ...btnStyle, gridRow: 'span 2', backgroundColor: '#3a3a3a', fontSize: '1.8rem' }}>▼</button>

                {/* Row 4 */}
                <button onClick={handleDel} style={{ ...btnStyle, backgroundColor: '#444' }}>
                    <span style={{ fontSize: '1.8rem', lineHeight: 1 }}>←</span>
                </button>
                <button onClick={() => handleKey('0')} style={btnStyle}>0</button>
                <button onClick={onClose} style={{ ...btnStyle, backgroundColor: '#d32f2f' }}>OK</button>
            </div>
        </div>
    );
}

const btnStyle: React.CSSProperties = {
    padding: '10px 0',
    fontSize: '24px',
    fontWeight: 'bold',
    borderRadius: '8px',
    border: '1px solid rgba(255,255,255,0.1)',
    backgroundColor: '#2a2a2a',
    color: '#fff',
    cursor: 'pointer',
    boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center'
};
