package example;

public final class AccountRule {
    public boolean canViewProfile(long viewerId, long profileOwnerId) {
        return viewerId == profileOwnerId;
    }
}
