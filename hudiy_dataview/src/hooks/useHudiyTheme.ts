import { useEffect, useState } from 'react';
import { Socket } from 'socket.io-client';

// Hudiy provides a Material You-like color palette
export interface HudiyColorScheme {
    primary?: string;
    onSurface?: string;
    darkThemeEnabled?: boolean;
    background?: string;
    surface?: string;
    onBackground?: string;
    primaryContainer?: string;
    onPrimaryContainer?: string;
    surfaceVariant?: string;
    onSurfaceVariant?: string;
    outline?: string;
    outlineVariant?: string;
    secondaryFixed?: string;
    tertiaryFixed?: string;
    error?: string;
    surfaceTint?: string;
    errorContainer?: string;
    [key: string]: any; // Catch-all for any other variables Hudiy sends
}

interface HudiyObj {
    colorScheme: HudiyColorScheme;
    onColorSchemeChanged?: () => void;
    onAttached?: () => void;
}

declare global {
    interface Window {
        hudiy?: HudiyObj;
    }
}

const DEFAULT_DEV_THEME: HudiyColorScheme = {
    primary: '#ff3b3b',
    onSurface: '#ffffff',
    darkThemeEnabled: true,
    background: '#121212',
    surface: '#1e1e1e',
    surfaceContainer: '#1d2024',
    surfaceDim: '#141414',
    onBackground: '#e0e0e0',
    primaryContainer: '#6b0000',
    onPrimaryContainer: '#ffdad6',
    surfaceVariant: '#444444',
    onSurfaceVariant: '#c4c4c4',
    outline: '#8c8c8c',
    outlineVariant: '#444444',
    secondaryFixed: '#ffcd2e', // Gold/Yellow
    tertiaryFixed: '#ff8a2e',  // Orange
    error: '#ff3b3b',           // Red (Primary)
    surfaceTint: '#ff3b3b',     // Often same as primary
    errorContainer: '#93000a'
};

export function useHudiyTheme(socket: Socket | null) {
    const [theme, setTheme] = useState<HudiyColorScheme>(DEFAULT_DEV_THEME);

    // Listen for mock themes emitted from the server (especially useful in Vite dev mode
    // where window.hudiy wasn't injected natively or by Jinja)
    useEffect(() => {
        if (!socket) return;

        const onStatus = (data: any) => {
            if (data.mock_theme) {
                console.log("Applying Mock Theme from backend", data.mock_theme);
                if (!window.hudiy) {
                    window.hudiy = { colorScheme: data.mock_theme };
                } else {
                    window.hudiy.colorScheme = data.mock_theme;
                    if (window.hudiy.onColorSchemeChanged) {
                        window.hudiy.onColorSchemeChanged();
                    }
                }
                setTheme(data.mock_theme);
            }
        };

        socket.on('status', onStatus);

        return () => {
            socket.off('status', onStatus);
        };
    }, [socket]);

    useEffect(() => {
        const attachHudiyListeners = () => {
            if (!window.hudiy) return;

            const h = window.hudiy;

            const updateColors = () => {
                if (h.colorScheme) {
                    if (socket) {
                        socket.emit('log_theme', h.colorScheme);
                    }
                    setTheme({ ...h.colorScheme });
                }
            };

            const originalColorChanged = h.onColorSchemeChanged;
            const originalAttached = h.onAttached;

            h.onColorSchemeChanged = () => {
                updateColors();
                if (originalColorChanged) originalColorChanged();
            };

            h.onAttached = () => {
                updateColors();
                if (originalAttached) originalAttached();
            };

            // Run once
            updateColors();

            return () => {
                h.onColorSchemeChanged = originalColorChanged;
                h.onAttached = originalAttached;
            };
        };

        // Try attaching immediately in case it exists.
        const cleanup = attachHudiyListeners();

        // If it was created later by our socket mock, we need to know. 
        // We handle that directly in the socket.on('status') block by calling setTheme, 
        // so we don't strictly need a mutation observer here.

        return () => {
            if (cleanup) cleanup();
        };
    }, []);

    return { theme };
}
