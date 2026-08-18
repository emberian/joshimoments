use tokio::sync::mpsc;

/// A bounded handoff. Full capacity is surfaced to the source runner, which must open a coverage
/// gap and reconnect/backfill; it is never converted into a silent drop.
#[derive(Clone, Debug)]
pub struct BoundedIngress<T> {
    sender: mpsc::Sender<T>,
}

#[derive(Debug)]
pub enum IngressError<T> {
    Full(T),
    Closed(T),
}

impl<T> BoundedIngress<T> {
    /// Create a bounded source handoff.
    ///
    /// # Panics
    ///
    /// Panics when `capacity` is zero because an always-full queue cannot preserve evidence.
    #[must_use]
    pub fn channel(capacity: usize) -> (Self, mpsc::Receiver<T>) {
        assert!(capacity > 0, "source ingress must be bounded above zero");
        let (sender, receiver) = mpsc::channel(capacity);
        (Self { sender }, receiver)
    }

    #[must_use]
    pub fn remaining_capacity(&self) -> usize {
        self.sender.capacity()
    }

    /// Attempt to hand off an item without waiting or dropping it.
    ///
    /// # Errors
    ///
    /// Returns the original item when the bounded channel is full or closed.
    pub fn try_send(&self, item: T) -> Result<(), IngressError<T>> {
        self.sender.try_send(item).map_err(|error| match error {
            mpsc::error::TrySendError::Full(item) => IngressError::Full(item),
            mpsc::error::TrySendError::Closed(item) => IngressError::Closed(item),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_channel_returns_the_unwritten_item() {
        let (ingress, _receiver) = BoundedIngress::channel(1);
        ingress.try_send(1).unwrap();
        assert!(matches!(ingress.try_send(2), Err(IngressError::Full(2))));
    }
}
