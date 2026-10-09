import { useEffect } from 'react';
import { useMotionValue, useTransform, motion } from 'framer-motion';
import { DataStore } from '../store/DataStore';

interface LiveTextProps {
  groupKey?: string;
  index?: number;
  valueId?: string;
  format?: (val: number | string) => string;
  className?: string;
}

export function LiveText({ groupKey = '', index = 0, valueId, format, className }: LiveTextProps) {
  // We use a MotionValue to hold the raw value outside of React State
  const mv = useMotionValue<number | string>(valueId ? '--' : 0);
  const key = valueId ? `value:${valueId}` : groupKey;
    const fieldIndex = valueId ? 0 : index;
  
  // Create a transformed motion value that applies our formatting
  const displayValue = useTransform(mv, (latest) => {
    if (latest === '--') return '--';
    if (format) return format(latest);
    // Default format: fix numbers to 1 decimal place, leave strings alone
    if (typeof latest === 'number') return latest.toFixed(1);
    return latest;
  });

  useEffect(() => {
    // Subscribe our MotionValue to only this specific data point inside the DataStore
        const unsubscribe = DataStore.subscribeValue(key, fieldIndex, (latestValue) => {
      mv.set(latestValue);
    });
    return unsubscribe;
    }, [key, fieldIndex, mv]);

  // Render a framer-motion span that reads from the transformed MotionValue natively
  return <motion.span className={className}>{displayValue}</motion.span>;
}

// Hook variant if you need the raw motion value for a style/transform property
export function useLiveValue(groupKey: string, index: number, initialValue: number | string = 0, valueId?: string) {
  const key = valueId ? `value:${valueId}` : groupKey;
    const fieldIndex = valueId ? 0 : index;
  const mv = useMotionValue<number | string>(valueId ? '--' : initialValue);
  useEffect(() => {
        return DataStore.subscribeValue(key, fieldIndex, (latestValue) => {
      mv.set(latestValue);
    });
    }, [key, fieldIndex, mv]);
  return mv;
}
