import { useEffect } from 'react';
import { useMotionValue, useTransform, motion } from 'framer-motion';
import { DataStore } from '../store/DataStore';

interface LiveTextProps {
  groupKey: string;
  index: number;
  format?: (val: number | string) => string;
  className?: string;
}

export function LiveText({ groupKey, index, format, className }: LiveTextProps) {
  // We use a MotionValue to hold the raw value outside of React State
  const mv = useMotionValue<number | string>(0);
  
  // Create a transformed motion value that applies our formatting
  const displayValue = useTransform(mv, (latest) => {
    if (format) return format(latest);
    // Default format: fix numbers to 1 decimal place, leave strings alone
    if (typeof latest === 'number') return latest.toFixed(1);
    return latest;
  });

  useEffect(() => {
    // Subscribe our MotionValue to only this specific data point inside the DataStore
    const unsubscribe = DataStore.subscribeValue(groupKey, index, (latestValue) => {
      mv.set(latestValue);
    });
    return unsubscribe;
  }, [groupKey, index, mv]);

  // Render a framer-motion span that reads from the transformed MotionValue natively
  return <motion.span className={className}>{displayValue}</motion.span>;
}

// Hook variant if you need the raw motion value for a style/transform property
export function useLiveValue(groupKey: string, index: number, initialValue: number | string = 0) {
  const mv = useMotionValue<number | string>(initialValue);
  useEffect(() => {
    return DataStore.subscribeValue(groupKey, index, (latestValue) => {
      mv.set(latestValue);
    });
  }, [groupKey, index, mv]);
  return mv;
}
